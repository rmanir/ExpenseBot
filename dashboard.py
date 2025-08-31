import os
import pandas as pd
import streamlit as st
import gspread
import plotly.express as px
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Expense Dashboard",
    page_icon="💸",
    layout="wide",
)

# ------------------- Data Fetching -------------------

@st.cache_data(ttl=60)  # refresh cached data every 60s
def fetch_data_from_sheets():
    """
    Fetches all data from all monthly sheets and combines them into a single DataFrame.
    Expects columns: Amount, Date, Type (Debit/Credit), Notes, Category
    """
    SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        st.error(f"Service account JSON not found at: {SERVICE_ACCOUNT_FILE}")
        return pd.DataFrame()
    if not SPREADSHEET_ID:
        st.error("GOOGLE_SHEETS_SPREADSHEET_ID is not set in environment/.env")
        return pd.DataFrame()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    all_data = []
    for ws in spreadsheet.worksheets():
        # Assumes a header row in first row
        records = ws.get_all_records()
        if records:
            all_data.extend(records)

    if not all_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_data)

    # Normalize columns
    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    else:
        df["Amount"] = 0.0

    # Fill missing required columns if any
    for col in ["Date", "Type", "Notes", "Category"]:
        if col not in df.columns:
            df[col] = ""

    # Clean and standardize Category text, convert HTML entity if present
    df["Category"] = (
        df["Category"].astype(str).str.replace("&amp;", "&", regex=False).str.strip()
    )
    df.dropna(subset=["Amount"], inplace=True)

    return df

# ------------------- Need/Want/Investment Computation -------------------

# Category sets (add variants if your sheet uses slightly different spellings)
NEED_CATS = {
    "Rent", "Grocery", "Petrol", "EB & EC", "Water & Gas", "Gas & Water",
    "Travel", "Medicine"
}
WANT_CATS = {"Entertainment"}
INVEST_CATS = {"Investment"}

def compute_need_want_invest(df: pd.DataFrame):
    """
    Computes allocation buckets (Need, Want, Investment) and their percentages of total income.
    Rules:
      - Investment rows (Category == 'Investment') -> Investment
      - Need rows: Rent, Grocery, Petrol, EB & EC, Water & Gas, Travel, Medicine
      - Want rows: Entertainment
      - Others category: split 50% to Need and 50% to Want
      - Income = sum of Amount for rows where Type == 'Credit'
      - Spending only counts rows where Type == 'Debit'
    """
    if df.empty:
        return 0.0, pd.DataFrame(columns=["Bucket", "Amount", "% of Income"])

    # Normalize helpers
    type_series = df["Type"].astype(str).str.lower()
    cat = df["Category"].astype(str)

    amount = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)

    # Income is total Credit
    income = amount[type_series.eq("credit")].sum()

    # Spending rows only
    spend_mask = type_series.eq("debit")
    spend_amt = amount.where(spend_mask, 0.0)

    # Base buckets
    need_amt = spend_amt[cat.isin(NEED_CATS)].sum()
    want_amt = spend_amt[cat.isin(WANT_CATS)].sum()
    invest_amt = spend_amt[cat.isin(INVEST_CATS)].sum()

    # Handle Others split (50% Need, 50% Want)
    known = NEED_CATS | WANT_CATS | INVEST_CATS
    others_mask = ~cat.isin(known)
    others_amt = spend_amt[others_mask].sum()
    need_amt += 0.5 * others_amt
    want_amt += 0.5 * others_amt

    denom = float(income) if income and income > 0 else 1.0  # avoid div/0
    summary = pd.DataFrame({
        "Bucket": ["Need", "Want", "Investment"],
        "Amount": [need_amt, want_amt, invest_amt],
    })
    summary["% of Income"] = (summary["Amount"] / denom * 100.0).round(2)
    return float(income), summary

# ------------------- UI -------------------

st.title("💸 Personal Expense Dashboard")
st.markdown("Your real-time financial overview, powered by Google Sheets.")

# Fetch data
df = fetch_data_from_sheets()

if df.empty:
    st.info("Waiting for data or no transactions found in your Google Sheet.")
    st.stop()

# --- KPIs ---
total_debit = df[df["Type"].astype(str).str.lower().eq("debit")]["Amount"].sum()
total_credit = df[df["Type"].astype(str).str.lower().eq("credit")]["Amount"].sum()
net_flow = total_credit - total_debit

c1, c2, c3 = st.columns(3)
c1.metric("💰 Total Debit", f"₹{total_debit:,.2f}")
c2.metric("📈 Total Credit", f"₹{total_credit:,.2f}")
c3.metric("⚖️ Net Flow", f"₹{net_flow:,.2f}")

st.markdown("---")

# --- Category charts ---
left, right = st.columns([2, 1])

with left:
    st.subheader("📊 Expenses by Category")
    category_expenses = (
        df[df["Type"].astype(str).str.lower().eq("debit")]
        .groupby("Category")["Amount"]
        .sum()
        .sort_values(ascending=False)
    )
    if not category_expenses.empty:
        fig = px.bar(
            category_expenses,
            x=category_expenses.index,
            y="Amount",
            title="Spending per Category",
            labels={"Amount": "Total Amount (₹)", "index": "Category"},
            text_auto=".2s",
        )
        fig.update_traces(textposition="outside")
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
income, nwi = compute_need_want_invest(df)
st.subheader("🧭 Allocation: Need vs Want vs Investment (as % of Income)")

m1, m2, m3, m4 = st.columns(4)
m1.metric("🏦 Income", f"₹{income:,.2f}")
need_amt = float(nwi.loc[nwi["Bucket"] == "Need", "Amount"].iloc[0]) if not nwi.empty else 0.0
want_amt = float(nwi.loc[nwi["Bucket"] == "Want", "Amount"].iloc[0]) if not nwi.empty else 0.0
inv_amt  = float(nwi.loc[nwi["Bucket"] == "Investment", "Amount"].iloc[0]) if not nwi.empty else 0.0
need_pct = float(nwi.loc[nwi["Bucket"] == "Need", "% of Income"].iloc[0]) if not nwi.empty else 0.0
want_pct = float(nwi.loc[nwi["Bucket"] == "Want", "% of Income"].iloc[0]) if not nwi.empty else 0.0
inv_pct  = float(nwi.loc[nwi["Bucket"] == "Investment", "% of Income"].iloc[0]) if not nwi.empty else 0.0

m2.metric("🧩 Need", f"₹{need_amt:,.2f}", f"{need_pct:.2f}%")
m3.metric("🎉 Want", f"₹{want_amt:,.2f}", f"{want_pct:.2f}%")
m4.metric("📈 Investment", f"₹{inv_amt:,.2f}", f"{inv_pct:.2f}%")

# Show target-aware colored badges under each metric (50/30/20 rule)
TARGETS = {"Need": 50.0, "Want": 30.0, "Investment": 20.0}

def pct_badge(bucket: str, pct: float) -> str:
    targ = TARGETS[bucket]
    # Investment good when >= target; Need/Want good when <= target
    if bucket == "Investment":
        color = "green" if pct >= targ else "red"
    else:
        color = "green" if pct <= targ else "red"
    return f":{color}-background[{pct:.2f}%]"

# Place badges directly under the three metrics
st.markdown(pct_badge("Need", need_pct))
st.markdown(pct_badge("Want", want_pct))
st.markdown(pct_badge("Investment", inv_pct))



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

    # Optional table
    st.dataframe(
        nwi.style.format({"Amount": "₹{:,.2f}", "% of Income": "{:.2f}%"}),
        use_container_width=True,
    )

st.markdown("---")

# --- Raw Data Table ---
st.subheader("🧾 All Transactions")
st.dataframe(df, use_container_width=True)
