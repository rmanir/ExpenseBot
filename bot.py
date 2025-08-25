import os
import re
from datetime import datetime
import pytz

# Stabilize timezone
os.environ.setdefault("TZ", "Asia/Kolkata")

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import gspread
from google.oauth2.service_account import Credentials

# ---------- Environment ----------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

if not BOT_TOKEN:
    raise RuntimeError("Error: TELEGRAM_BOT_TOKEN is not set in .env")
if not SPREADSHEET_ID:
    raise RuntimeError("Error: GOOGLE_SHEETS_SPREADSHEET_ID is not set in .env")

IST = pytz.timezone("Asia/Kolkata")
HEADERS = ["Amount", "Date", "Type", "Notes"]

# ---------- Google Sheets ----------
def get_client_and_spreadsheet():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise RuntimeError(f"Service account JSON not found at: {SERVICE_ACCOUNT_FILE}")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return gc, sh

def ensure_headers_and_format(ws):
    """Ensure headers exist, bold + centered, and freeze first row."""
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if [h.strip() for h in (first_row or [])] != HEADERS:
        ws.update("A1:D1", [HEADERS])
    # Bold + center headers and freeze row 1
    ws.format("A1:D1", {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"})
    try:
        ws.freeze(rows=1)
    except Exception:
        pass

def get_or_create_month_sheet(sh, month_title: str):
    """Get or create a worksheet titled 'Month Year' with formatted headers."""
    try:
        ws = sh.worksheet(month_title)
        ensure_headers_and_format(ws)
        return ws
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=month_title, rows=1000, cols=10)
        ws.update("A1:D1", [HEADERS])
        ws.format("A1:D1", {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"})
        try:
            ws.freeze(rows=1)
        except Exception:
            pass
        return ws

# ---------- Parsing helpers (tagged text, spaces allowed after tags) ----------
TAG_A = re.compile(r"(?<!\S)[aA]\s*([0-9][0-9,\.]*?)\b")
TAG_T = re.compile(r"(?<!\S)[tT]\s*([cCdD])\b")
TAG_N = re.compile(r"(?<!\S)[nN]\s*(.+?)(?=\s+[aAnNtT]\b|$)")

def clean_amount(s: str) -> str:
    """Keep digits, commas, optional dot; normalize to integer if .00 else 2 decimals."""
    if not s:
        return "-"
    s = re.sub(r"[^0-9,\.]", "", s)
    if not s:
        return "-"
    try:
        val = float(s.replace(",", ""))
        if val.is_integer():
            return f"{int(val):,}"
        else:
            return f"{val:,.2f}"
    except Exception:
        s2 = re.sub(r"[^0-9,]", "", s)
        if not s2:
            return "-"
        try:
            val2 = int(s2.replace(",", ""))
            return f"{val2:,}"
        except Exception:
            return s2

def clean_notes(s: str) -> str:
    """Keep letters, numbers, spaces only; collapse whitespace."""
    if not s:
        return "-"
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or "-"

def map_type(ch: str) -> str:
    """C/c -> CREDIT, D/d -> DEBIT, else '-'."""
    if not ch:
        return "-"
    ch = ch.strip().upper()
    if ch == "C":
        return "CREDIT"
    if ch == "D":
        return "DEBIT"
    return "-"

def parse_tagged_text(text: str):
    """Parse: a <amount> n <notes> t <type> (order flexible, case-insensitive)."""
    s = re.sub(r"[ \t]+", " ", text or "").strip()
    amt_match = TAG_A.search(s)
    amount = clean_amount(amt_match.group(1) if amt_match else "-")
    type_match = TAG_T.search(s)
    txn_type = map_type(type_match.group(1) if type_match else "")
    note_match = TAG_N.search(s)
    notes = clean_notes(note_match.group(1) if note_match else "-")
    return amount, txn_type, notes

# ---------- Telegram handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Send a tagged text to log a transaction (case‑insensitive; spaces allowed after tags):\n"
        "Format: a <amount> n <notes> t <type>\n"
        "Examples:\n"
        "• a 1580 n Brush t D\n"
        "• A 1,250 N fuel T c\n"
        "Type: t D = DEBIT, t C = CREDIT\n"
        "Entries are saved in a monthly sheet named 'Month Year' (e.g., 'August 2025')."
    )
    await update.message.reply_text(msg)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, sh = get_client_and_spreadsheet()

        # Parse incoming text
        text = update.message.text or ""
        amount, txn_type, notes = parse_tagged_text(text)

        # IST date and Month Year title
        now_ist = datetime.now(IST)
        date_str = now_ist.strftime("%Y-%m-%d")
        month_title = now_ist.strftime("%B %Y")  # e.g., "August 2025"

        # Target worksheet (auto-create + format headers if needed)
        ws = get_or_create_month_sheet(sh, month_title)

        # Append exactly 4 columns (Amount, Date, Type, Notes)
        ws.append_row([amount, date_str, txn_type, notes], value_input_option="USER_ENTERED")

        # Minimal reply
        await update.message.reply_text(
            "✅ Saved\n"
            f"Amount: {amount}\n"
            f"Notes: {notes}\n"
            f"Timestamp: {date_str}\n"
            f"Type: {txn_type}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use tagged text format:\n"
        "a <amount> n <notes> t <type>\n"
        "Example: a 1580 n Brush t D"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.run_polling()

if __name__ == "__main__":
    main()
