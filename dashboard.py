import os
import random
import time
from datetime import datetime
import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

# Load environment variables
load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Expense Dashboard",
    page_icon="💸",
    layout="wide",
)

# --- Constants & Targets ---
NEED_CATS = {
    "Rent", "Grocery", "Petrol", "EB & EC", "Water & Gas", "Gas & Water",
    "Travel", "Medicine"
}
WANT_CATS = {"Entertainment"}
INVEST_CATS = {"Investment"}
TARGETS = {"Need": 50.0, "Want": 30.0, "Investment": 20.0}

# --- Data Fetching ---
@st.cache_resource(ttl=600)
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

def get_spreadsheet():
    """Get the main spreadsheet object."""
    client = get_gspread_client()
    if client is None:
        return None
    SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not SPREADSHEET_ID:
        st.error("GOOGLE_SHEETS_SPREADSHEET_ID is not set in environment/.env")
        return None
    try:
        return client.open_by_key(SPREADSHEET_ID)
    except SpreadsheetNotFound:
        st.error("Spreadsheet not found. Check the SPREADSHEET_ID and sharing permissions.")
        return None
    except APIError as e:
        st.error(f"API Error fetching spreadsheet: {e}")
        return None

def load_sheet_data(ws):
    """Load data from a single worksheet into a DataFrame with retry logic and normalized columns."""
    max_retries = 5
    base_delay = 1 # in seconds
    for attempt in range(max_retries):
        try:
            records = ws.get_all_records()
            if not records:
                return pd.DataFrame()
            df = pd.DataFrame(records)
            # --- Normalize Columns ---
            df["Amount"] = pd.to_numeric(df.get("Amount"), errors="coerce").fillna(0)
            for col in ["Date", "Type", "Notes", "Category"]:
                if col not in df.columns:
                    df[col] = ""
            df["Category"] = df["Category"].astype(str).str.strip()
            df.dropna(subset=["Amount"], inplace=True)
            return df
        except APIError as e:
            if e.response.status_code in [429, 503] and attempt < max_retries - 1:
                delay = (base_delay * 2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
            else:
                st.error(f"Failed to fetch data from '{ws.title}'. Error: {e}")
                return pd.DataFrame()
    return pd.DataFrame()

@st.cache_data(ttl=600)
def load_budget_data(_spreadsheet, year):
    """Load budget data for a specific year."""
    try:
        budget_sheet_name = f"Budget {year}"
        ws = _spreadsheet.worksheet(budget_sheet_name)
        data = ws.get_all_values()
        if len(data) < 2:
            return None, None # Not enough data
        header = data[0]
        df = pd.DataFrame(data[1:], columns=header)
        # Separate target from actuals
        target_df = df[df['Month'].str.lower() == 'target'].copy()
        actuals_df = df[df['Month'].str.lower() != 'target'].copy()
        # Convert to numeric, coercing errors
        for col in df.columns:
            if col != 'Month':
                target_df[col] = pd.to_numeric(target_df[col], errors='coerce').fillna(0)
                actuals_df[col] = pd.to_numeric(actuals_df[col], errors='coerce').fillna(0)
        if target_df.empty:
            return None, actuals_df # No target row found
        return target_df.iloc[0], actuals_df
    except WorksheetNotFound:
        st.warning(f"Budget sheet '{budget_sheet_name}' not found.")
        return None, None
    except Exception as e:
        st.error(f"An error occurred while loading budget data: {e}")
        return None, None

# ----------- Computations -----------
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

# ----------- UI -----------
st.title("💸 Personal Expense Dashboard")
st.markdown("Your real-time financial overview, powered by Google Sheets.")

spreadsheet = get_spreadsheet()
if spreadsheet is None:
    st.stop()

worksheets = [ws for ws in spreadsheet.worksheets() if "budget" not in ws.title.lower()]
if not worksheets:
    st.warning("No monthly expense sheets found.")
    st.stop()

# --- OPTIMIZATION: Load budget data once outside the loop ---
current_year = datetime.now().year
target_budget, actuals_df = load_budget_data(spreadsheet, current_year)

# Create tabs for each sheet
tab_names = [ws.title for ws in worksheets]
tabs = st.tabs(tab_names)

for ws, tab in zip(worksheets, tabs):
    with tab:
        st.header(f"📑 {ws.title}")
        df = load_sheet_data(ws)
        if df.empty:
            st.info("No transactions found in this sheet.")
            continue

        # --- KPIs ---
        total_debit = df[df["Type"].astype(str).str.lower() == "debit"]["Amount"].sum()
        total_credit = df[df["Type"].astype(str).str.lower() == "credit"]["Amount"].sum()
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
            df[df["Type"].astype(str).str.lower() == "debit"]
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
                    color=category_expenses.index,
                    title="Spending per Category",
                    labels={"Amount": "Total Amount (₹)", "index": "Category"},
                    text_auto=".2s",
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True, key=f"category_bar_{ws.title}")
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
                st.plotly_chart(fig_pie, use_container_width=True, key=f"category_pie_{ws.title}")
            else:
                st.info("No debit transactions to plot distribution.")
        st.markdown("---")

        # --- NEW: Budget vs Actuals Section ---
        st.subheader("🎯 Budget vs. Actuals")
        if target_budget is not None and actuals_df is not None:
            # Extract only the month name (e.g., "August") from the tab title (e.g., "August 2025")
            current_month_name = ws.title.split(" ")[0]
            
            # Filter the annual actuals to only the current tab's month
            monthly_actuals_row = actuals_df[actuals_df['Month'].str.strip().str.lower() == current_month_name.strip().lower()]
            
            # Get the data for the month; if it doesn't exist, use a series of zeros
            if not monthly_actuals_row.empty:
                actuals_for_month = monthly_actuals_row.iloc[0].drop('Month')
            else:
                actuals_for_month = pd.Series(0, index=target_budget.index.drop('Month'))
                
            # Create a combined DataFrame for plotting with the correct monthly data
            budget_comparison_df = pd.DataFrame({
                'Category': target_budget.index.drop('Month'),
                'Target': target_budget.drop('Month').values,
                'Actual': actuals_for_month.reindex(target_budget.index.drop('Month')).fillna(0).values
            })
            
            if not budget_comparison_df.empty:
                fig_budget = go.Figure()
                fig_budget.add_trace(go.Bar(
                    x=budget_comparison_df['Category'],
                    y=budget_comparison_df['Target'],
                    name='Target',
                    marker_color='lightsalmon'
                ))
                fig_budget.add_trace(go.Bar(
                    x=budget_comparison_df['Category'],
                    y=budget_comparison_df['Actual'],
                    name='Actual',
                    marker_color='indianred'
                ))
                
                # Update the title to be month-specific
                fig_budget.update_layout(
                    barmode='group',
                    title_text=f'Budget vs. Actual Spending for {ws.title}',
                    xaxis_title="Category",
                    yaxis_title="Amount (₹)"
                )
                
                # Add the unique key to prevent the duplicate ID error
                st.plotly_chart(fig_budget, use_container_width=True, key=f"budget_chart_{ws.title}")
            else:
                st.info("No data available to display budget comparison.")
        else:
            st.info(f"Could not load budget data for {current_year} to create comparison chart.")
            
        # --- Need / Want / Investment allocation ---
        st.subheader("🧭 Allocation: Need vs Want vs Investment (as % of Income)")
        
        def delta_vs_target(bucket: str, pct: float) -> str:
            targ = TARGETS[bucket]
            raw_diff = round(pct - targ, 2)
            abs_diff = abs(raw_diff)
            if bucket == "Investment":
                sign = "↑" if pct >= targ else "↓"
            else: # For Need and Want, lower is better or on target
                sign = "↓" if pct <= targ else "↑"
            return f"{sign}{abs_diff:.2f}%"
            
        income_nwi, nwi = compute_need_want_invest(df)
        nwi_display = nwi.copy()
        nwi_display["Target Amount"] = nwi_display["Bucket"].map(lambda b: income_nwi * TARGETS[b] / 100.0)
        nwi_display["Over/(Under) Target"] = nwi_display["Amount"] - nwi_display["Target Amount"]
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🏦 Income", f"₹{income_nwi:,.2f}")
        
        for bucket, col in zip(["Need", "Want", "Investment"], [m2, m3, m4]):
            row = nwi[nwi["Bucket"] == bucket]
            if not row.empty:
                amt = float(row["Amount"].iloc[0])
                pct = float(row["% of Income"].iloc[0])
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
            st.plotly_chart(fig_nwi, use_container_width=True, key=f"nwi_pie_{ws.title}")
            
            nwi_display = nwi_display[["Bucket", "Amount", "% of Income", "Target Amount", "Over/(Under) Target"]].set_index("Bucket")
            
            def highlight_over_under_row(row):
                bucket = row.name
                val = row["Over/(Under) Target"]
                # Green if good, Red if bad
                if bucket == "Investment":
                    color = "#e6f4ea" if val >= 0 else "#fdecea" # Green for over, Red for under
                else:
                    color = "#e6f4ea" if val <= 0 else "#fdecea" # Green for under, Red for over
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
        
        # --- All Transactions ---
        st.subheader("🧾 All Transactions")
        st.dataframe(df, use_container_width=True)
