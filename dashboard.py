import os
import random
import time

import gspread
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

# Load environment variables
load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Expense Dashboard",
    page_icon="💸",
    layout="wide",
)

# ------------------- Data Fetching -------------------
@st.cache_resource(ttl=600)  # Cache the client for 10 minutes
def get_gspread_client():
    """Create and cache the gspread client."""
    SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        st.error(f"Service account JSON not found at: {SERVICE_ACCOUNT_FILE}")
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds)

def fetch_sheets():
    """Fetch worksheet objects from the spreadsheet."""
    client = get_gspread_client()
    if client is None:
        return []

    SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not SPREADSHEET_ID:
        st.error("GOOGLE_SHEETS_SPREADSHEET_ID is not set in environment/.env")
        return []

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        return spreadsheet.worksheets()
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Spreadsheet not found. Check the SPREADSHEET_ID and sharing permissions.")
        return []
    except APIError as e:
        st.error(f"API Error fetching spreadsheet: {e}")
        return []

def load_sheet_data(ws):
    """Load data from a single worksheet into a DataFrame with retry logic and normalized columns."""
    max_retries = 5
    base_delay = 1  # in seconds

    for attempt in range(max_retries):
        try:
            records = ws.get_all_records()
            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)
            if "Amount" in df.columns:
                df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
            else:
                df["Amount"] = 0.0

            for col in ["Date", "Type", "Notes", "Category"]:
                if col not in df.columns:
                    df[col] = ""

            df["Category"] = (
                df["Category"].astype(str).str.replace("&", "&", regex=False).str.strip()
            )
            df.dropna(subset=["Amount"], inplace=True)
            return df

        except APIError as e:
            if e.response.status_code == 503 and attempt < max_retries - 1:
                delay = (base_delay * 2**attempt) + random.uniform(0, 1)
                st.warning(f"API Error 503 fetching data from '{ws.title}'. Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
            else:
                st.error(f"Failed to fetch data from '{ws.title}' after {max_retries} attempts. Last error: {e}")
                return pd.DataFrame()

    return pd.DataFrame()

# ------------------- Need/Want/Investment Computation -------------------
NEED_CATS = {
    "Rent", "Grocery", "Petrol", "EB & EC", "Water & Gas", "Gas & Water",
    "Travel", "Medicine"
}
WANT_CATS = {"Entertainment"}
INVEST_CATS = {"Investment"}

def compute_need_want_invest(df: pd.DataFrame):
    if df.empty:
        return 0.0, pd.DataFrame(columns=["Bucket", "Amount", "% of Income"])

    type_series = df["Type"].astype(str).str.lower()
    cat = df["Category"].astype(str)
    amount = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    income = amount[type_series.eq("credit")].sum()

    spend_mask = type_series.eq("debit")
    spend_amt = amount.where(spend_mask, 0.0)

    need_amt = spend_amt[cat.isin(NEED_CATS)].sum()
    want_amt = spend_amt[cat.isin(WANT_CATS)].sum()
    invest_amt = spend_amt[cat.isin(INVEST_CATS)].sum()

    known = NEED_CATS | WANT_CATS | INVEST_CATS
    others_amt = spend_amt[~cat.isin(known)].sum()

    # Split "Others" category spending between Need and Want
    need_amt += 0.5 * others_amt
    want_amt += 0.5 * others_amt

    denom = float(income) if income > 0 else 1.0
    summary = pd.DataFrame({
        "Bucket": ["Need", "Want", "Investment"],
        "Amount": [need_amt, want_amt, invest_amt],
    })
    summary["% of Income"] = (summary["Amount"] / denom * 100.0).round(2)
    return float(income), summary

# ------------------- UI -------------------
st.title("💸 Personal Expense Dashboard")
st.markdown("Your real-time financial overview, powered by Google Sheets.")

worksheets = fetch_sheets()
if not worksheets:
    st.stop()

# Create tabs for each sheet
tab_names = [ws.title for ws in worksheets]
tabs = st.tabs(tab_names)

for ws, tab in zip(worksheets, tabs):
    with tab:
        st.header(f"📑 {ws.title}")
        df = load_sheet_data(ws)

        if df.empty:
            st.info("No transactions found in this sheet or failed to load data.")
            continue

        # --- KPIs ---
        total_debit = df[df["Type"].astype(str).str.lower().eq("debit")]["Amount"].sum()
        total_credit = df[df["Type"].astype(str).str.lower().eq("credit")]["Amount"].sum()
        net_flow = total_credit - total_debit
        income = float(total_credit)
        pct_of_income = (net_flow / income * 100.0) if income > 0 else 0.0
        sign = "+" if pct_of_income >= 0 else ""
        net_flow_delta = f"{sign}{pct_of_income:.2f}% of income"

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Total Expenses", f"₹{total_debit:,.2f}")
        c2.metric("📈 Total Income", f"₹{total_credit:,.2f}")
        c3.metric("⚖️ Difference", f"₹{net_flow:,.2f}", net_flow_delta)
        st.markdown("---")

        # --- Category charts ---
        left, right = st.columns([2, 1])
        category_expenses = (
            df[df["Type"].astype(str).str.lower().eq("debit")]
            .groupby("Category")["Amount"]
            .sum()
            .sort_values(ascending=False)
        )

        with left:
            st.subheader("📊 Expenses by Category")
            if not category_expenses.empty:
                fig = px.bar(
                    category_expenses,
                    x=category_expenses.index,
                    y="Amount",
                    color=category_expenses.index, # Use category for color
                    title="Spending per Category",
                    labels={"Amount": "Total Amount (₹)", "index": "Category"},
                    text_auto=".2s",
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(showlegend=False) # Hide the legend
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No debit transactions to chart by category.")

        with right:
            st.subheader("🥧 Category Distribution")
            if not category_expenses.empty:
                fig_pie = px.pie(
                    category_expenses,
                    values="Amount",
                    names=category_expenses.index,
                    title="Expense Proportions",
                    hole=0.3,
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("No debit transactions to plot distribution.")

        st.markdown("---")

        # --- Need / Want / Investment allocation ---
        TARGETS = {"Need": 50.0, "Want": 30.0, "Investment": 20.0}

        def delta_vs_target(bucket: str, pct: float) -> str:
            targ = TARGETS[bucket]
            raw_diff = round(pct - targ, 2)
            abs_diff = abs(raw_diff)
            if bucket == "Investment":
                sign = "+" if pct >= targ else "-"
            else: # For Need and Want, lower is better or on target
                sign = "+" if pct <= targ else "-"
            return f"{sign}{abs_diff:.2f}%"

        income_nwi, nwi = compute_need_want_invest(df)
        st.subheader("🧭 Allocation: Need vs Want vs Investment (as % of Income)")
        nwi_display = nwi.copy()
        nwi_display["Target Amount"] = nwi_display["Bucket"].map(lambda b: income_nwi * TARGETS[b] / 100.0)
        nwi_display["Over/(Under) Target"] = nwi_display["Amount"] - nwi_display["Target Amount"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🏦 Income", f"₹{income_nwi:,.2f}")

        for bucket, col in zip(["Need", "Want", "Investment"], [m2, m3, m4]):
            if not nwi[nwi["Bucket"] == bucket].empty:
                amt = float(nwi.loc[nwi["Bucket"] == bucket, "Amount"].iloc[0])
                pct = float(nwi.loc[nwi["Bucket"] == bucket, "% of Income"].iloc[0])
                col.metric(bucket, f"₹{amt:,.2f}", delta_vs_target(bucket, pct))
            else:
                col.metric(bucket, "₹0.00", delta_vs_target(bucket, 0.0))

        if not nwi.empty:
            fig_nwi = px.pie(
                nwi,
                values="% of Income",
                names="Bucket",
                title="Allocation (% of Income)",
                hole=0.45,
                color="Bucket",
                color_discrete_map={"Need": "#1f77b4", "Want": "#ff7f0e", "Investment": "#2ca02c"},
            )
            fig_nwi.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig_nwi, use_container_width=True)

            nwi_display = nwi_display[["Bucket", "Amount", "% of Income", "Target Amount", "Over/(Under) Target"]].set_index("Bucket")

            def highlight_over_under_row(row):
                bucket = row.name
                val = row["Over/(Under) Target"]
                # Green if good, Red if bad
                if bucket == "Investment":
                    color = "#e6f4ea" if val >= 0 else "#fdecea"  # Green for over, Red for under
                else:
                    color = "#e6f4ea" if val <= 0 else "#fdecea"  # Green for under, Red for over
                return ["background-color: %s" % color for _ in row.index]


            styled = (
                nwi_display.style
                .format({
                    "Amount": "₹{:,.2f}",
                    "Target Amount": "₹{:,.2f}",
                    "Over/(Under) Target": "₹{:+,.2f}",
                    "% of Income": "{:.2f}%"
                })
                .apply(highlight_over_under_row, axis=1)
            )
            st.dataframe(styled, use_container_width=True)

        st.markdown("---")
        st.subheader("🧾 All Transactions")
        st.dataframe(df, use_container_width=True)

