#!/usr/bin/env python3
"""
ExpenseBot for scheduled runs (hybrid shutdown: idle OR max runtime).
Features:
- Polling-based Telegram bot (python-telegram-bot v22.3)
- Writes to Google Sheets (monthly sheets created automatically)
- Supports raw JSON or base64 service account secret (GOOGLE_SERVICE_ACCOUNT env var)
- Prevents duplicates, supports /editlast and /delete
- Parses simple and tagged formats
- Hybrid shutdown: stops after IDLE_SECONDS of inactivity OR RUN_MINUTES of runtime
"""

import os
import json
import base64
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

import pytz
import gspread
from google.oauth2 import service_account

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------- Configuration ----------
RUN_MINUTES = int(os.getenv("RUN_MINUTES", "60"))  # auto-shutdown in minutes (max runtime)
IDLE_SECONDS = int(os.getenv("IDLE_SECONDS", "15"))  # stop early when no new updates seen
TIMEZONE = os.getenv("TZ", "Asia/Kolkata")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SA_SECRET = os.getenv("GOOGLE_SERVICE_ACCOUNT")  # raw JSON or base64

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")
if not SPREADSHEET_ID:
    raise RuntimeError("SPREADSHEET_ID env var is required")
if not SA_SECRET:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT env var is required (raw JSON or base64)")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# Global to track last activity timestamp
_last_activity = time.time()
# Lock for updating last activity
_activity_lock = threading.Lock()

def touch_activity():
    global _last_activity
    with _activity_lock:
        _last_activity = time.time()

def time_since_last_activity() -> float:
    with _activity_lock:
        return time.time() - _last_activity

# ---------- Utils: Service account load (supports raw JSON or base64) ----------
def load_service_account(info_str: str) -> Dict[str, Any]:
    """Attempt to parse the provided string as JSON or base64(JSON)."""
    # Try direct JSON
    try:
        return json.loads(info_str)
    except Exception:
        pass
    # Try base64
    try:
        decoded = base64.b64decode(info_str)
        return json.loads(decoded.decode("utf-8"))
    except Exception as e:
        log.error("Failed to decode GOOGLE_SERVICE_ACCOUNT: %s", e)
        raise

# ---------- Google Sheets helpers ----------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def get_gspread_client() -> gspread.Client:
    info = load_service_account(SA_SECRET)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client

def month_sheet_title_for_date(dt: datetime) -> str:
    # Example: "Nov 2025"
    return dt.strftime("%b %Y")

def ensure_month_sheet(wb: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return wb.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        # create with headers
        sh = wb.add_worksheet(title=title, rows="1000", cols="20")
        headers = ["Timestamp", "Date", "Amount", "Notes", "Category", "Type", "TelegramUser"]
        sh.append_row(headers)
        return sh

def fetch_recent_rows(sh: gspread.Worksheet, n: int = 200) -> List[List[str]]:
    vals = sh.get_all_values()
    if not vals:
        return []
    # exclude header
    return vals[1:][-n:]

def is_duplicate(sh: gspread.Worksheet, date_s: str, amount_s: str, notes: str, typ: str) -> bool:
    recent = fetch_recent_rows(sh, 500)
    for r in recent:
        # columns: Timestamp, Date, Amount, Notes, Category, Type, TelegramUser
        if len(r) < 6:
            continue
        _, d, a, n, _, t, *_ = (r + [""] * 7)
        if a.strip() == amount_s.strip() and n.strip().lower() == notes.strip().lower() and d.strip() == date_s.strip() and t.strip().lower() == typ.strip().lower():
            return True
    return False

# ---------- Basic category auto-assign ----------
CATEGORY_KEYWORDS = {
    "grocery": ["grocery", "groceries", "supermarket", "bigbasket", "kgf"],
    "petrol": ["fuel", "petrol", "diesel", "gas", "bpcl", "hpcl"],
    "rent": ["rent", "room", "house"],
    "travel": ["uber", "ola", "taxi", "bus", "train", "flight", "kiger", "car petrol", "redbus", "cab"],
    "medicine": ["pharmacy", "doctor", "hospital", "medicine"],
    "entertainment": ["netflix", "prime", "movie", "tea", "coffee", "dosa", "breakfast", "lunch", "dinner", "restaurant", "food", "eats", "snacks"],
    "eb & ec" : ["eb", "recharge", "current bill", "wifi"],
    "Water & Gas" : ["water", "gas"],
    "investment" : ["stock", "gold"],
    "income" : ["salary", "pons"]
}

def assign_category(notes: str) -> str:
    n = notes.lower()
    for cat, keys in CATEGORY_KEYWORDS.items():
        for k in keys:
            if k in n:
                return cat.capitalize()
    return "Misc"

# ---------- Message parsing ----------
def parse_date_token(tok: str) -> Optional[str]:
    """
    Accepts dd-mm-yyyy, dd-mm-yy, dd-mm
    Returns normalized date string dd-mm-yyyy
    """
    tok = tok.strip()
    for fmt in ("%d-%m-%Y", "%d-%m-%y", "%d-%m"):
        try:
            dt = datetime.strptime(tok, fmt)
            if fmt == "%d-%m":
                # assume current year in TIMEZONE
                tz = pytz.timezone(TIMEZONE)
                year = datetime.now(tz).year
                dt = dt.replace(year=year)
            return dt.strftime("%d-%m-%Y")
        except Exception:
            continue
    return None

def parse_tagged(text: str) -> Optional[Dict[str,str]]:
    """
    Tagged format: a <amount> n <notes> t <type> d <date (optional)>
    tokens can be in any order; tags a/n/t/d
    """
    toks = text.strip().split()
    out = {"amount": "", "notes": "", "type": "", "date": ""}
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.lower() in ("a", "n", "t", "d"):
            key = t.lower()
            i += 1
            val_parts = []
            while i < len(toks) and toks[i].lower() not in ("a","n","t","d"):
                val_parts.append(toks[i])
                i += 1
            out_map = {"a":"amount","n":"notes","t":"type","d":"date"}
            out[out_map[key]] = " ".join(val_parts).strip()
        else:
            # malformed - skip token
            i += 1
    # validate amount and type
    if not out["amount"]:
        return None
    # try parse amount numeric
    try:
        float(out["amount"].replace(",",""))
    except Exception:
        return None
    # parse date if present
    if out["date"]:
        dd = parse_date_token(out["date"])
        if not dd:
            return None
        out["date"] = dd
    else:
        # default today's date (in IST)
        out["date"] = datetime.now(pytz.timezone(TIMEZONE)).strftime("%d-%m-%Y")
    # normalize type
    if out["type"]:
        t = out["type"].strip().lower()
        out["type"] = "Debit" if t.startswith("d") else ("Credit" if t.startswith("c") else "")
    else:
        out["type"] = "Debit"
    return out

def parse_simple(text: str) -> Optional[Dict[str,str]]:
    """
    Simple: <amount> <notes> <type>
    type must be last token (d/D or c/C)
    """
    toks = text.strip().split()
    if len(toks) < 2:
        return None
    last = toks[-1]
    typ = None
    if last.lower() in ("d","debit"):
        typ = "Debit"
        notes = " ".join(toks[1:-1]) if len(toks) > 2 else (toks[1] if len(toks)==2 else "")
    elif last.lower() in ("c","credit"):
        typ = "Credit"
        notes = " ".join(toks[1:-1]) if len(toks) > 2 else (toks[1] if len(toks)==2 else "")
    else:
        # maybe user gave no type; treat as debit and everything after amount as notes
        typ = "Debit"
        notes = " ".join(toks[1:])
    # amount
    try:
        amt = toks[0].replace(",","")
        float(amt)
    except Exception:
        return None
    date_s = datetime.now(pytz.timezone(TIMEZONE)).strftime("%d-%m-%Y")
    return {"amount": amt, "notes": notes.strip(), "type": typ, "date": date_s}

def parse_message(text: str) -> Optional[Dict[str,str]]:
    # try tagged first
    tagged = parse_tagged(text)
    if tagged:
        return tagged
    # try simple
    simple = parse_simple(text)
    if simple:
        return simple
    return None

# ---------- Bot responses ----------
START_MESSAGE = """🤖 Expense Tracker Bot

📝 Two formats supported:

1. Simple format (for today's date):
amount notes type
Example: 500 Tea d

2. Tagged format (with optional date):
a <amount> n <notes> t <type> d <date>
Example: a 1580 n Brush t d d 28-08-2025

Tags & Types:
• a - Amount
• n - Notes
• t - Type (d/D for Debit, c/C for Credit)
• d - Date (Optional). Accepts dd-mm-yyyy, dd-mm-yy, or dd-mm.

Entries are saved in monthly sheets. Categories are auto-assigned! 🎯
"""

INVALID_MESSAGE = """❌ Invalid format

Use either:
• 500 Tea d (simple)
• a 500 n Tea t d d (tagged)

Send /start for more details
"""

def format_saved_reply(amount: str, notes: str, date_s: str, category: str, typ: str) -> str:
    # e.g.
    # ✅ Saved Successfully!
    # 💰 Amount: ₹110
    # 📝 Notes: grocery
    # 📅 Date: 2025-11-15
    # 📂 Category: Grocery
    # 🔖 Type: Debit
    return (
        "✅ Saved Successfully!\n\n"
        f"💰 Amount: ₹{amount}\n"
        f"📝 Notes: {notes}\n"
        f"📅 Date: {date_s}\n"
        f"📂 Category: {category}\n"
        f"🔖 Type: {typ}"
    )

# ---------- Handlers ----------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_MESSAGE)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_MESSAGE)

async def invalid_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(INVALID_MESSAGE)

async def delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Deletes the last entry in the current month's sheet.
    """
    client = context.bot_data.get("gclient")
    wb = context.bot_data.get("workbook")
    if not client or not wb:
        await update.message.reply_text("Google Sheets not connected.")
        return
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    sheet_title = month_sheet_title_for_date(now)
    sh = ensure_month_sheet(wb, sheet_title)
    vals = sh.get_all_values()
    if len(vals) <= 1:
        await update.message.reply_text("No entries to delete.")
        return
    last_row_index = len(vals)  # 1-based including header
    sh.delete_rows(last_row_index)
    await update.message.reply_text("✅ Last entry deleted.")
    touch_activity()

async def edit_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /editlast <new entry in same input format>
    Edits the last row in current month sheet with new parsed data.
    """
    txt = update.message.text or ""
    rest = txt[len("/editlast"):].strip()
    if not rest:
        await update.message.reply_text("Usage: /editlast <new entry in same format>\nExample: /editlast 500 Tea d")
        return
    parsed = parse_message(rest)
    if not parsed:
        await update.message.reply_text(INVALID_MESSAGE)
        return
    client = context.bot_data.get("gclient")
    wb = context.bot_data.get("workbook")
    if not client or not wb:
        await update.message.reply_text("Google Sheets not connected.")
        return
    tz = pytz.timezone(TIMEZONE)
    dt = datetime.now(tz)
    sheet_title = month_sheet_title_for_date(dt)
    sh = ensure_month_sheet(wb, sheet_title)
    vals = sh.get_all_values()
    if len(vals) <= 1:
        await update.message.reply_text("No entries to edit.")
        return
    # prepare row content
    timestamp = datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    category = assign_category(parsed["notes"])
    new_row = [timestamp, parsed["date"], parsed["amount"], parsed["notes"], category, parsed["type"], update.message.from_user.first_name]
    # update last row
    last_row_index = len(vals)
    sh.delete_rows(last_row_index)
    sh.append_row(new_row)
    await update.message.reply_text("✅ Last entry updated.\n\n" + format_saved_reply(parsed["amount"], parsed["notes"], parsed["date"], category, parsed["type"]))
    touch_activity()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text(INVALID_MESSAGE)
        return
    parsed = parse_message(text)
    if not parsed:
        await update.message.reply_text(INVALID_MESSAGE)
        return
    # Connect to Google client from context
    client = context.bot_data.get("gclient")
    wb = context.bot_data.get("workbook")
    if not client or not wb:
        await update.message.reply_text("Google Sheets not connected on this run. Try again later.")
        return
    # determine target sheet
    try:
        dt = datetime.strptime(parsed["date"], "%d-%m-%Y")
    except Exception:
        dt = datetime.now(pytz.timezone(TIMEZONE))
    sheet_title = month_sheet_title_for_date(dt)
    sh = ensure_month_sheet(wb, sheet_title)
    # duplicate prevention
    if is_duplicate(sh, parsed["date"], parsed["amount"], parsed["notes"], parsed["type"]):
        await update.message.reply_text("⚠️ Duplicate detected — entry ignored.")
        touch_activity()
        return
    # append row
    timestamp = datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    category = assign_category(parsed["notes"])
    row = [timestamp, parsed["date"], parsed["amount"], parsed["notes"], category, parsed["type"], update.message.from_user.first_name]
    sh.append_row(row)
    await update.message.reply_text(format_saved_reply(parsed["amount"], parsed["notes"], parsed["date"], category, parsed["type"]))
    touch_activity()

# ---------- Startup and application ----------
def create_application(gclient, workbook) -> Application:
    application = Application.builder().token(BOT_TOKEN).build()
    # store clients in bot_data for handlers
    application.bot_data["gclient"] = gclient
    application.bot_data["workbook"] = workbook

    # handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("delete", delete_last))
    application.add_handler(CommandHandler("editlast", edit_last))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    return application

def monitor_and_stop(app: Application, start_time: float):
    """
    Monitor thread: stops the app when ANY of:
    - idle timeout reached (no activity for IDLE_SECONDS)
    - max runtime exceeded (RUN_MINUTES)
    - app is None or not running
    """
    log.info("Monitor thread started: max %d minutes, idle %d seconds.", RUN_MINUTES, IDLE_SECONDS)
    while True:
        # check runtime
        elapsed = (time.time() - start_time)
        if elapsed >= RUN_MINUTES * 60:
            log.info("Max runtime %d minutes reached (%.1f seconds). Exiting.", RUN_MINUTES, elapsed)
            try:
                # graceful stop of polling then hard exit
                app.stop()
            except Exception:
                log.exception("Error while stopping app gracefully.")
            time.sleep(1)
            os._exit(0)
        # check idle
        if time_since_last_activity() >= IDLE_SECONDS:
            log.info("Idle timeout: no activity for %d seconds. Exiting.", IDLE_SECONDS)
            try:
                app.stop()
            except Exception:
                log.exception("Error while stopping app gracefully on idle.")
            time.sleep(1)
            os._exit(0)
        time.sleep(1)

def run_bot():
    # Setup Google client and workbook
    gclient = get_gspread_client()
    wb = gclient.open_by_key(SPREADSHEET_ID)
    log.info("✅ Google Sheets connected (spreadsheet id=%s).", SPREADSHEET_ID)

    # Build app
    app = create_application(gclient, wb)

    # set initial activity to now
    touch_activity()
    start_time = time.time()

    # Start monitor thread
    t = threading.Thread(target=monitor_and_stop, args=(app, start_time), daemon=True)
    t.start()

    # Start polling (blocking). When os._exit runs, process ends.
    log.info("🤖 Bot starting (max %d minutes, idle %d seconds)...", RUN_MINUTES, IDLE_SECONDS)
    app.run_polling()

if __name__ == "__main__":
    try:
        run_bot()
    except SystemExit:
        log.info("SystemExit called - exiting.")
    except Exception as exc:
        log.exception("Bot crashed: %s", exc)
        raise
