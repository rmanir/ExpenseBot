import os
import random
import time
import json
import base64
from datetime import datetime

import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

# =========================================================
# 🔐 STREAMLIT CLOUD – SERVICE ACCOUNT LOADING (base64 or JSON)
# =========================================================
def load_service_account():
    """Load service account from Streamlit Secrets (base64 or raw JSON)."""
    sa_raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT")
    if not sa_raw:
        st.error("GOOGLE_SERVICE_ACCOUNT missing in Streamlit Secrets.")
        st.stop()

    # Try raw JSON
    try:
        return json.loads(sa_raw)
    except:
        pass

    # Try base64(JSON)
    try:
        decoded = base64.b64decode(sa_raw).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        st.error(f"Failed to decode GOOGLE_SERVICE_ACCOUNT: {e}")
        st.stop()

# =========================================================
# STREAMLIT PAGE CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="Expense Dashboard",
    page_icon="💸",
    layout="wide",
)

st.title("💸 Personal Expense Dashboard")
st.markdown("Your real-time financial overview, powered by Google Sheets.")

# =========================================================
# CATEGORY GROUPS & TARGETS
# =========================================================
NEED_CATS = {
    "Rent", "Grocery", "Petrol", "EB & EC", "Gas & Water",
    "Travel", "Medicine"
}
WANT_CATS = {"Entertainment"}
INVEST_CATS = {"Investment, Emergency Fund"}
TARGETS = {"Need": 50.0, "Want": 30.0, "Investment": 20.0}

# =========================================================
# GOOGLE SHEETS CONNECTION
# =========================================================
@st.cache_resource(ttl=600)
def get_gspread_client():
    info = load_service_account()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def get_spreadsheet():
    client = get_gspread_client()

    SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID")
    if not SPREADSHEET_ID:
        st.error("SPREADSHEET_ID missing in Streamlit Secrets.")
        st.stop()

    try:
        return client.open_by_key(SPREADSHEET_ID)
    except SpreadsheetNotFound:
        st.error("Spreadsheet not found. Verify SPREADSHEET_ID and sharing permissions.")
        st.stop()
    except APIError as e:
        st.error(f"Google Sheets API Error: {e}")
        st.stop()

# =========================================================
# LOAD INDIVIDUAL SHEET
# =========================================================
def load_sheet_data(ws):
    """Load data from a worksheet into a clean DataFrame."""
    retries = 5
    for attempt in range(retries):
        try:
            data = ws.get_all_records()
            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)

            # Normalize expected columns
            df["Amount"] = pd.to_numeric(df.get("Amount"), errors="coerce").fillna(0)
            for col in ["Date", "Type", "Notes", "Category"]:
                if col not in df.columns:
                    df[col] = ""

            df["Category"] = df["Category"].astype(str).str.strip()
            df.dropna(subset=["Amount"], inplace=True)
            return df

        except APIError as e:
            if attempt < retries - 1 and e.response.status_code in [429, 503]:
                time.sleep(1.5 ** attempt)
                continue
            st.error(f"Error reading sheet {ws.title}: {e}")
            return pd.DataFrame()

# =========================================================
# LOAD BUDGET SHEET
# =========================================================
@st.cache_data(ttl=600)
def load_budget_data(spreadsheet_id):
    name = f"Budget"
    try:
        ws = spreadsheet.worksheet(name)
        raw = ws.get_all_values()
        if len(raw) < 2:
            return None, None

        df = pd.DataFrame(raw[1:], columns=raw[0])
        target = df[df["Month"].str.lower() == "target"]
        actual = df[df["Month"].str.lower() != "target"]

        # Convert numeric columns
        for col in df.columns:
            if col != "Month":
                target[col] = pd.to_numeric(target[col], errors="coerce").fillna(0)
                actual[col] = pd.to_numeric(actual[col], errors="coerce").fillna(0)

        if target.empty:
            return None, actual

        return target.iloc[0], actual

    except WorksheetNotFound:
        st.warning(f"{name} not found.")
        return None, None

# =========================================================
# NEED / WANT / INVEST CALCULATIONS
# =========================================================
def compute_need_want_invest(df):
    if df.empty:
        return 0, pd.DataFrame(columns=["Bucket", "Amount", "% of Income"])

    type_col = df["Type"].astype(str).str.lower()
    cat = df["Category"].astype(str)
    amt = df["Amount"]

    income = amt[type_col == "credit"].sum()
    spend = amt.where(type_col == "debit", 0)

    need = spend[cat.isin(NEED_CATS)].sum()
    want = spend[cat.isin(WANT_CATS)].sum()
    invest = spend[cat.isin(INVEST_CATS)].sum()
    others = spend[~cat.isin(NEED_CATS | WANT_CATS | INVEST_CATS)].sum()

    need += others * 0.5
    want += others * 0.5

    denom = income if income > 0 else 1

    summary = pd.DataFrame({
        "Bucket": ["Need", "Want", "Investment"],
        "Amount": [need, want, invest],
    })
    summary["% of Income"] = (summary["Amount"] / denom * 100).round(2)

    return income, summary

# =========================================================
# FETCH SPREADSHEET
# =========================================================
spreadsheet = get_spreadsheet()
worksheets = [ws for ws in spreadsheet.worksheets() if "budget" not in ws.title.lower()]

if not worksheets:
    st.warning("No monthly sheets found.")
    st.stop()

current_year = datetime.now().year
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"] 
target_budget, actuals_df = load_budget_data(SPREADSHEET_ID, current_year)

# =========================================================
# RENDER TABS
# =========================================================
tabs = st.tabs([ws.title for ws in worksheets])

for ws, tab in zip(worksheets, tabs):
    with tab:
        st.header(f"📑 {ws.title}")
        df = load_sheet_data(ws)
        if df.empty:
            st.info("No records in this sheet.")
            continue

        # KPIs
        total_debit = df[df["Type"].str.lower() == "debit"]["Amount"].sum()
        total_credit = df[df["Type"].str.lower() == "credit"]["Amount"].sum()
        net = total_credit - total_debit
        pct = (net / total_credit * 100) if total_credit else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Total Expenses", f"₹{total_debit:,.2f}")
        c2.metric("📈 Total Income", f"₹{total_credit:,.2f}")
        c3.metric("⚖️ Difference", f"₹{net:,.2f}", f"{pct:+.2f}%")

        st.markdown("---")

        # CATEGORY BAR & PIE
        debit_cats = (
            df[df["Type"].str.lower() == "debit"]
            .groupby("Category")["Amount"].sum()
            .sort_values(ascending=False)
        )

        left, right = st.columns([2, 1])

        with left:
            st.subheader("📊 Expenses by Category")
            if not debit_cats.empty:
                fig = px.bar(
                    debit_cats,
                    x=debit_cats.index,
                    y="Amount",
                    color=debit_cats.index,
                    text_auto=".2s",
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No debit data to visualize.")

        with right:
            st.subheader("🥧 Category Distribution")
            if not debit_cats.empty:
                st.plotly_chart(
                    px.pie(debit_cats, values="Amount", names=debit_cats.index, hole=0.3),
                    use_container_width=True,
                )
            else:
                st.info("No data available.")

        st.markdown("---")

        # =========================================================
        # BUDGET VS ACTUAL
        # =========================================================
        st.subheader("🎯 Budget vs Actuals")

        if target_budget is not None and actuals_df is not None:
            month_name = ws.title.split()[0].lower()
            row = actuals_df[actuals_df["Month"].str.lower() == month_name]

            actual = (
                row.iloc[0].drop("Month")
                if not row.empty
                else pd.Series(0, index=target_budget.index.drop("Month"))
            )

            comp = pd.DataFrame({
                "Category": target_budget.index.drop("Month"),
                "Target": target_budget.drop("Month").values,
                "Actual": actual.values,
            })

            fig = go.Figure()
            fig.add_bar(x=comp["Category"], y=comp["Target"], name="Target", marker_color="lightsalmon")
            fig.add_bar(x=comp["Category"], y=comp["Actual"], name="Actual", marker_color="indianred")
            fig.update_layout(barmode="group", title=f"Budget vs Actual – {ws.title}")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No budget data available for this year.")

        st.markdown("---")

        # =========================================================
        # NEED / WANT / INVEST SECTION
        # =========================================================
        st.subheader("🧭 Need / Want / Investment")

        income_nwi, nwi = compute_need_want_invest(df)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🏦 Income", f"₹{income_nwi:,.2f}")

        def delta(bucket, pct):
            target = TARGETS[bucket]
            diff = pct - target
            sign = "↑" if diff > 0 else "↓"
            return f"{sign}{abs(diff):.2f}%"

        for bucket, col in zip(["Need", "Want", "Investment"], [m2, m3, m4]):
            row = nwi[nwi["Bucket"] == bucket]
            amt = float(row["Amount"].iloc[0])
            pct = float(row["% of Income"].iloc[0])
            col.metric(bucket, f"₹{amt:,.2f}", delta(bucket, pct))

        st.plotly_chart(
            px.pie(nwi, values="% of Income", names="Bucket", hole=0.45),
            use_container_width=True,
        )

        st.markdown("---")

        # ALL TRANSACTIONS
        st.subheader("🧾 All Transactions")
        st.dataframe(df, use_container_width=True)
