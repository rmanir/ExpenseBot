# =========================================================
# 💸 PERSONAL FINANCE DASHBOARD – STREAMLIT
# =========================================================
import json, base64, time, re
from datetime import datetime

import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Personal Finance Dashboard",
    page_icon="💸",
    layout="wide",
)

st.title("💸 Personal Finance Dashboard")

# =========================================================
# SERVICE ACCOUNT LOADER
# =========================================================
def load_service_account():
    raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT")
    if not raw:
        st.error("GOOGLE_SERVICE_ACCOUNT missing")
        st.stop()
    try:
        return json.loads(raw)
    except:
        return json.loads(base64.b64decode(raw).decode())

# =========================================================
# GOOGLE SHEETS CLIENT
# =========================================================
@st.cache_resource
def get_client():
    creds = Credentials.from_service_account_info(
        load_service_account(),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return gspread.authorize(creds)

@st.cache_resource
def get_spreadsheet():
    return get_client().open_by_key(st.secrets["SPREADSHEET_ID"])

# =========================================================
# LOADERS
# =========================================================
@st.cache_data(ttl=300)
def load_month(sheet_name):
    ws = get_spreadsheet().worksheet(sheet_name)
    df = pd.DataFrame(ws.get_all_records())
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    df["Type"] = df["Type"].str.lower()
    df["Category"] = df["Category"].str.strip()
    return df

@st.cache_data(ttl=300)
def load_category_total():
    ws = get_spreadsheet().worksheet("category total")
    raw = ws.get_all_values()
    df = pd.DataFrame(raw[1:], columns=raw[0])
    df = df.set_index("Category")
    return df.apply(pd.to_numeric, errors="coerce").fillna(0)

@st.cache_data(ttl=300)
def load_budget():
    ws = get_spreadsheet().worksheet("Budget")
    raw = ws.get_all_values()

    if len(raw) < 2:
        st.warning("Budget sheet is empty.")
        return pd.Series(dtype=float)

    df = pd.DataFrame(raw[1:], columns=raw[0])

    # Normalize
    df["Month"] = df["Month"].astype(str).str.strip().str.lower()

    target = df[df["Month"] == "target"]
    if target.empty:
        st.warning("Target row not found in Budget sheet.")
        return pd.Series(dtype=float)

    target_row = target.iloc[0].drop("Month")

    # Convert safely to numeric
    target_row = pd.to_numeric(target_row, errors="coerce").fillna(0)

    return target_row

# =========================================================
# YEAR & MONTH DISCOVERY
# =========================================================
spreadsheet = get_spreadsheet()
monthly_sheets = [
    ws.title for ws in spreadsheet.worksheets()
    if re.match(r".*\d{4}", ws.title)
]

years = sorted({s.split()[-1] for s in monthly_sheets})
year = st.selectbox("Select Year", years)

months = [s for s in monthly_sheets if s.endswith(year)]
month = st.selectbox("Select Month", months)

# =========================================================
# LOAD DATA
# =========================================================
df_month = load_month(month)
cat_total = load_category_total()
budget = load_budget()

# =========================================================
# KPI SECTION
# =========================================================
income = cat_total.loc["Income", month]
expense = cat_total[month].sum() - income
diff = income - expense

c1, c2, c3 = st.columns(3)
c1.metric("Income", f"₹{income:,.0f}")
c2.metric("Expense", f"₹{expense:,.0f}")

arrow = "↑" if diff >= 0 else "↓"
color = "green" if diff >= 0 else "red"
c3.markdown(
    f"<h2 style='color:{color}'>₹{diff:,.0f} {arrow}</h2>",
    unsafe_allow_html=True,
)

st.divider()

# =========================================================
# CATEGORY BAR CHART
# =========================================================
st.subheader("📊 Category-wise Spend")
cat_exp = cat_total[month].drop("Income")
st.plotly_chart(
    px.bar(
        cat_exp.sort_values(ascending=False),
        labels={"value": "Amount", "index": "Category"},
    ),
    use_container_width=True,
)

st.divider()

# =========================================================
# BUDGET VS ACTUAL
# =========================================================
st.subheader("🎯 Budget vs Actual")

rows = []

for cat in budget.index:
    target = budget.get(cat, 0)

    # SAFE lookup – default to 0 if missing
    actual = (
        cat_total.at[cat, month]
        if cat in cat_total.index and month in cat_total.columns
        else 0
    )

    rows.append({
        "Category": cat,
        "Target": target,
        "Actual": actual,
        "Color": "green" if actual <= target else "red"
    })

budget_df = pd.DataFrame(rows)

fig = go.Figure()
fig.add_bar(
    x=budget_df["Category"],
    y=budget_df["Target"],
    name="Target",
    marker_color="lightgray"
)
fig.add_bar(
    x=budget_df["Category"],
    y=budget_df["Actual"],
    name="Actual",
    marker_color=budget_df["Color"]
)

fig.update_layout(
    barmode="group",
    title=f"Budget vs Actual – {month}",
    xaxis_title="Category",
    yaxis_title="Amount",
)

st.plotly_chart(fig, use_container_width=True)

st.divider()

# =========================================================
# NEED / WANT / INVEST
# =========================================================
st.subheader("🧭 Needs / Wants / Investment")

others = cat_total.loc["Others", month]
needs = (
    cat_total.loc[
        ["Rent", "Grocery", "EB & EC", "Gas & Water", "Petrol", "Travel"],
        month
    ].sum() + others / 2
)

wants = cat_total.loc["Entertainment", month] + others / 2
investment = cat_total.loc["Investment", month]

def bucket(label, amount, limit, reverse=False):
    pct = amount / income * 100 if income else 0
    bad = pct < limit if reverse else pct > limit
    color = "red" if bad else "green"
    return f"<b>{label}</b><br>₹{amount:,.0f}<br><span style='color:{color}'>{pct:.1f}%</span>"

c1, c2, c3 = st.columns(3)
c1.markdown(bucket("Needs", needs, 50), unsafe_allow_html=True)
c2.markdown(bucket("Wants", wants, 30), unsafe_allow_html=True)
c3.markdown(bucket("Investment", investment, 20, reverse=True), unsafe_allow_html=True)

st.divider()

# =========================================================
# TRANSACTION TABLE
# =========================================================
st.subheader("🧾 Monthly Transactions")
st.dataframe(df_month, use_container_width=True)
