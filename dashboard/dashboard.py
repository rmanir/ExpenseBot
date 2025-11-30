import os
import base64
import json
import random
import time
from datetime import datetime

import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound


# =========================================================
#  STREAMLIT PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Expense Dashboard",
    page_icon="💸",
    layout="wide",
)


# =========================================================
#  LOAD GOOGLE CREDENTIALS (BASE64 → JSON FILE)
# =========================================================
SERVICE_JSON_PATH = "service_account.json"

def load_credentials():
    """Decode Base64 service account JSON from Streamlit secrets."""
    encoded = os.environ.get("GOOGLE_SERVICE_ACCOUNT_BASE64")

    if not encoded:
        st.error("Missing GOOGLE_SERVICE_ACCOUNT_BASE64 in Streamlit secrets.")
        st.stop()

    try:
        decoded = base64.b64decode(encoded)
        with open(SERVICE_JSON_PATH, "wb") as f:
            f.write(decoded)
        return SERVICE_JSON_PATH
    except Exception as e:
        st.error(f"Failed to decode Google credentials: {e}")
        st.stop()


# =========================================================
#  CONSTANTS
# =========================================================
NEED_CATS = {
    "Rent", "Grocery", "Petrol", "EB & EC", "Water & Gas",
    "Gas & Water", "Travel", "Medicine"
}
WANT_CATS = {"Entertainment"}
INVEST_CATS = {"Investment"}
TARGETS = {"Need": 50.0, "Want": 30.0, "Investment": 20.0}


# =========================================================
#  GOOGLE SHEETS CLIENT
# =========================================================
@st.cache_resource(ttl=600)
def get_gspread_client():
    """Create and cache the gspread client."""
    json_path = load_credentials()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file(json_path, scopes=scopes)
    return gspread.authorize(creds)


def get_spreadsheet():
    client = get_gspread_client()

    SPREADSHEET_ID = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not SPREADHEET_ID := SPREADSHEET_ID:
        st.error("Missing GOOGLE_SHEETS_SPREADSHEET_ID in Streamlit secrets.")
        st.stop()

    try:
        return client.open_by_key(SPREADSHEET_ID)
    except SpreadsheetNotFound:
        st.error("Spreadsheet not found. Check sharing permissions.")
        st.stop()
    except Exception as e:
        st.error(f"Error opening spreadsheet: {e}")
        st.stop()


# =========================================================
#  DATA LOADERS
# =========================================================
def load_sheet_data(ws):
    max_retries = 5
    base_delay = 1

    for attempt in range(max_retries):
        try:
            records = ws.get_all_records()
            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)
            df["Amount"] = pd.to_numeric(df.get("Amount"), errors="coerce").fillna(0)

            for col in ["Date", "Type", "Notes", "Category"]:
                if col not in df.columns:
                    df[col] = ""

            df["Category"] = df["Category"].astype(str).strip()
            df.dropna(subset=["Amount"], inplace=True)
            return df

        except APIError as e:
            if e.response.status_code in [429, 503] and attempt < max_retries - 1:
                delay = (base_delay * 2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
            else:
                st.error(f"Error loading sheet '{ws.title}': {e}")
                return pd.DataFrame()

    return pd.DataFrame()


@st.cache_data(ttl=600)
def load_budget_data(_spreadsheet, year):
    try:
        ws = _spreadsheet.worksheet(f"Budget {year}")
        data = ws.get_all_values()
        if len(data) < 2:
            return None, None

        header = data[0]
        df = pd.DataFrame(data[1:], columns=header)

        target_df = df[df["Month"].str.lower() == "target"]
        actuals_df = df[df["Month"].str.lower() != "target"]

        for col in header:
            if col != "Month":
                target_df[col] = pd.to_numeric(target_df[col], errors="coerce").fillna(0)
                actuals_df[col] = pd.to_numeric(actuals_df[col], errors="coerce").fillna(0)

        if target_df.empty:
            return None, actuals_df

        return target_df.iloc[0], actuals_df

    except WorksheetNotFound:
        return None, None
    except Exception as e:
        st.error(f"Error loading budget: {e}")
        return None, None


# =========================================================
#  COMPUTATION LOGIC
# =========================================================
def compute_need_want_invest(df):
    if df.empty:
        return 0.0, pd.DataFrame(columns=["Bucket", "Amount", "% of Income"])

    type_series = df["Type"].astype(str).str.lower()
    amount = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    cat = df["Category"].astype(str)

    income = amount[type_series.eq("credit")].sum()
    spend = amount.where(type_series.eq("debit"), 0)

    need_amt = spend[cat.isin(NEED_CATS)].sum()
    want_amt = spend[cat.isin(WANT_CATS)].sum()
    invest_amt = spend[cat.isin(INVEST_CATS)].sum()

    # Split Others 50-50
    known = NEED_CATS | WANT_CATS | INVEST_CATS
    others = spend[~cat.isin(known)].sum()
    need_amt += 0.5 * others
    want_amt += 0.5 * others

    denom = income if income > 0 else 1

    summary = pd.DataFrame({
        "Bucket": ["Need", "Want", "Investment"],
        "Amount": [need_amt, want_amt, invest_amt],
    })
    summary["% of Income"] = (summary["Amount"] / denom * 100).round(2)

    return income, summary


# =========================================================
#  UI START
# =========================================================
st.title("💸 Personal Expense Dashboard")
st.markdown("Your real-time financial overview, powered by Google Sheets.")


# =========================================================
#  LOAD SPREADSHEET
# =========================================================
spreadsheet = get_spreadsheet()
worksheets = [ws for ws in spreadsheet.worksheets() if "budget" not in ws.title.lower()]

if not worksheets:
    st.warning("No monthly sheets found.")
    st.stop()


current_year = datetime.now().year
target_budget, actuals_df = load_budget_data(spreadsheet, current_year)

tab_names = [ws.title for ws in worksheets]
tabs = st.tabs(tab_names)


# =========================================================
#  MAIN LOOP PER SHEET
# =========================================================
for ws, tab in zip(worksheets, tabs):
    with tab:
        st.header(f"📑 {ws.title}")

        df = load_sheet_data(ws)
        if df.empty:
            st.info("No transactions.")
            continue

        # ------- KPIs -------
        total_debit = df[df["Type"].str.lower() == "debit"]["Amount"].sum()
        total_credit = df[df["Type"].str.lower() == "credit"]["Amount"].sum()
        net_flow = total_credit - total_debit

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Expenses", f"₹{total_debit:,.2f}")
        c2.metric("📈 Income", f"₹{total_credit:,.2f}")
        c3.metric("⚖️ Net Flow", f"₹{net_flow:,.2f}")

        st.markdown("---")

        # ------- CATEGORY CHARTS -------
        left, right = st.columns([2, 1])
        cat_exp = (
            df[df["Type"].str.lower() == "debit"]
            .groupby("Category")["Amount"]
            .sum()
            .sort_values(ascending=False)
        )

        with left:
            st.subheader("📊 Expenses by Category")
            if not cat_exp.empty:
                fig = px.bar(
                    cat_exp,
                    x=cat_exp.index,
                    y="Amount",
                    text_auto=".2s",
                )
                fig.update_traces(textposition="outside")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No debit data.")

        with right:
            st.subheader("🥧 Distribution")
            if not cat_exp.empty:
                fig_pie = px.pie(cat_exp, values="Amount", names=cat_exp.index)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("No data.")

        st.markdown("---")

        # ------- BUDGET VS ACTUAL -------
        st.subheader("🎯 Budget vs Actual")

        if target_budget is not None and actuals_df is not None:
            month_name = ws.title.split(" ")[0].strip().lower()
            row = actuals_df[actuals_df["Month"].str.lower() == month_name]

            actual_for_month = row.iloc[0].drop("Month") if not row.empty else pd.Series(0, target_budget.index.drop("Month"))

            df_bud = pd.DataFrame({
                "Category": target_budget.index.drop("Month"),
                "Target": target_budget.drop("Month").values,
                "Actual": actual_for_month.values
            })

            fig = go.Figure()
            fig.add_bar(x=df_bud["Category"], y=df_bud["Target"], name="Target")
            fig.add_bar(x=df_bud["Category"], y=df_bud["Actual"], name="Actual")
            fig.update_layout(barmode="group")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # ------- NEED / WANT / INVEST -------
        st.subheader("🧭 Allocation Based on Income")

        income_nwi, nwi_df = compute_need_want_invest(df)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🏦 Income", f"₹{income_nwi:,.2f}")

        for bucket, col in zip(["Need", "Want", "Investment"], [m2, m3, m4]):
            row = nwi_df[nwi_df["Bucket"] == bucket]
            amt = float(row["Amount"]) if not row.empty else 0
            pct = float(row["% of Income"]) if not row.empty else 0
            col.metric(bucket, f"₹{amt:,.2f}", f"{pct:.2f}%")

        fig_nwi = px.pie(nwi_df, values="% of Income", names="Bucket", hole=0.45)
        st.plotly_chart(fig_nwi, use_container_width=True)

        st.markdown("---")

        # ------- FULL TABLE -------
        st.subheader("🧾 All Transactions")
        st.dataframe(df, use_container_width=True)
