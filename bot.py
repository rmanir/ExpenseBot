import os
import logging
import re
import time
from datetime import datetime
import asyncio
import pytz
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
from dotenv import load_dotenv

load_dotenv()

# Constants & config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
IST = pytz.timezone("Asia/Kolkata")
DUPLICATE_WINDOW_SECONDS = 10  # duplicate prevention window

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing in .env")
if not SPREADSHEET_ID:
    raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID missing in .env")
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    raise RuntimeError(f"service_account.json not found at: {SERVICE_ACCOUNT_FILE}")

# Category map (keeps same mapping as previous)
CATEGORY_MAP = {
    "rent": "Rent",
    "stock": "Investment",
    "insurance": "Investment",
    "gold": "Investment",
    "eb bill": "EB & EC",
    "recharge": "EB & EC",
    "internet bill": "EB & EC",
    "withdrawal": "Withdrawal",
    "petrol": "Petrol",
    "bus": "Travel",
    "irctc": "Travel",
    "kiger": "Travel",
    "fasttag": "Travel",
    "gas": "Gas & Water",
    "water": "Gas & Water",
    "grocery": "Grocery",
    "flour": "Grocery",
    "chicken": "Grocery",
    "coconut": "Grocery",
    "food": "Entertainment",
    "snacks": "Entertainment",
    "trip": "Entertainment",
    "medicine": "Medicine",
    "medical": "Medicine",
    "rice": "Grocery",
    "oil": "Grocery",
    "flower": "Grocery",
    "income": "Income",
    "salary": "Income",
    "investment": "Investment",
    "milk": "Grocery",
    "tea": "Entertainment",
    "icecream": "Entertainment",
    "car": "Travel"
}

# In-memory state for duplicate prevention and last operation per user
_last_message = {}  # user_id -> (text, timestamp)

# ================= Google Sheets helpers =================

def get_client_and_spreadsheet():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return client, spreadsheet


def ensure_headers_and_format(ws):
    headers = ["Amount", "Date", "Type", "Notes", "Category"]
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if [h.strip() for h in (first_row or [])] != headers:
        ws.update("A1:E1", [headers])
    try:
        ws.freeze(rows=1)
    except Exception:
        pass


def get_or_create_monthly_sheet(date_obj: datetime):
    month_year = date_obj.strftime("%B %Y")
    _, spreadsheet = get_client_and_spreadsheet()
    try:
        ws = spreadsheet.worksheet(month_year)
        ensure_headers_and_format(ws)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=month_year, rows=1200, cols=6)
        ws.append_row(["Amount", "Date", "Type", "Notes", "Category"])
        ensure_headers_and_format(ws)
        return ws

# ================= Parsing =================

def categorize(notes: str) -> str:
    notes_lower = (notes or "").lower()
    for key, cat in CATEGORY_MAP.items():
        if key in notes_lower:
            return cat
    return "Others"


def parse_simple_format(text: str):
    # simple: amount notes type  e.g. 500 tea d
    parts = text.strip().split()
    if len(parts) < 2:
        return None
    # amount first
    try:
        amount = float(parts[0].replace(',', ''))
    except Exception:
        return None
    tx_type = parts[-1].lower()
    if tx_type not in ["d", "c"]:
        return None
    notes = " ".join(parts[1:-1]) or ""
    tx_type_full = "Debit" if tx_type == 'd' else 'Credit'
    date_obj = datetime.now(IST)
    category = categorize(notes)
    return {
        'amount': amount,
        'notes': notes,
        'type': tx_type_full,
        'date': date_obj,
        'category': category
    }


def parse_tagged_format(text: str):
    # tagged: a <amount> n <notes> t <type> d <date>
    # order flexible; date optional
    tokens = text.strip().split()
    if len(tokens) < 1:
        return None
    data = {'amount': None, 'notes': '', 'type': None, 'date': None}
    i = 0
    while i < len(tokens):
        tok = tokens[i].lower()
        if tok == 'a' and i + 1 < len(tokens):
            try:
                data['amount'] = float(tokens[i+1].replace(',', ''))
                i += 2
                continue
            except Exception:
                return None
        if tok == 'n':
            # gather notes until next tag or end
            j = i+1
            notes_parts = []
            while j < len(tokens) and tokens[j].lower() not in ['a','n','t','d']:
                notes_parts.append(tokens[j])
                j += 1
            data['notes'] = ' '.join(notes_parts)
            i = j
            continue
        if tok == 't' and i + 1 < len(tokens):
            tkn = tokens[i+1].lower()
            if tkn in ['d', 'c', 'debit', 'credit']:
                data['type'] = 'Debit' if tkn.startswith('d') else 'Credit'
                i += 2
                continue
            else:
                return None
        if tok == 'd' and i + 1 < len(tokens):
            # date formats: dd-mm-yyyy, dd-mm-yy, dd-mm
            date_str = tokens[i+1]
            try:
                parts = date_str.split('-')
                day = int(parts[0])
                month = int(parts[1])
                year = None
                if len(parts) == 3:
                    year = int(parts[2])
                    if year < 100:  # yy
                        year += 2000
                else:
                    year = datetime.now(IST).year
                # create date
                data['date'] = datetime(year, month, day, tzinfo=IST)
                i += 2
                continue
            except Exception:
                return None
        # unrecognized token — move on
        i += 1
    if data['amount'] is None or data['type'] is None:
        return None
    if data['date'] is None:
        data['date'] = datetime.now(IST)
    data['category'] = categorize(data['notes'])
    return data


def parse_message(text: str):
    # try tagged first (if starts with 'a '), else simple
    text_strip = text.strip()
    if text_strip.lower().startswith('a '):
        return parse_tagged_format(text_strip)
    return parse_simple_format(text_strip)

# ================= Helpers =================

def format_success_message(entry: dict) -> str:
    # entry: amount, notes, type, date (datetime), category
    date_str = entry['date'].strftime('%Y-%m-%d')
    amt_str = f"₹{int(entry['amount']) if entry['amount'].is_integer() else entry['amount']}"
    return (
        "✅ Saved Successfully!\n\n"
        f"💰 Amount: {amt_str}\n"
        f"📝 Notes: {entry['notes'] or '-'}\n"
        f"📅 Date: {date_str}\n"
        f"📂 Category: {entry['category']}\n"
        f"🔖 Type: {entry['type']}"
    )


def get_last_data_row(ws):
    # returns index of last non-empty row (>=2). If only header exists, return None
    values = ws.get_all_values()
    if len(values) <= 1:
        return None
    return len(values)

# ================= Command Handlers =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📘 Expense Tracker Bot\n\n"
        "📝 Two formats supported:\n\n"
        "1. *Simple format* (for today's date):\n"
        "`amount notes type`\n"
        "Example: `500 Tea d`\n\n"
        "2. *Tagged format* (with optional date):\n"
        "`a <amount> n <notes> t <type> d <date>`\n"
        "Example: `a 1580 n Brush t d d 28-08-2025`\n\n"
        "*Tags & Types:*\n"
        "• `a` - Amount\n"
        "• `n` - Notes\n"
        "• `t` - Type (d/D for Debit, c/C for Credit)\n"
        "• `d` - Date (Optional). Accepts *dd-mm-yyyy*, *dd-mm-yy*, or *dd-mm*.\n\n"
        "Entries are saved in monthly sheets. Categories are auto-assigned! 🎯"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_invalid_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❌ *Invalid format*\n\n"
        "Use either:\n"
        "• `500 Tea d` *(simple)*\n"
        "• `a 500 n Tea t d` *(tagged)*\n\n"
        "Send /start for more details"
    )
    await update.message.reply_text(text, parse_mode="Markdown")



async def log_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id if user else None
        text = (update.message.text or "").strip()
        logger.info(f"RAW UPDATE MESSAGE from {user_id}: {text}")

        # Duplicate prevention (Option A with 5 sec)
        now_ts = time.time()
        last = _last_message.get(user_id)
        if last and last[0] == text and (now_ts - last[1]) <= DUPLICATE_WINDOW_SECONDS:
            await update.message.reply_text("⚠️ Duplicate entry ignored (sent too quickly).")
            return
        # update last message
        _last_message[user_id] = (text, now_ts)

        parsed = parse_message(text)
        if not parsed:
            await help_invalid_format(update, context)
            return

        # prepare sheet append
        ws = get_or_create_monthly_sheet(parsed['date'])
        date_str = parsed['date'].strftime('%Y-%m-%d')
        row = [parsed['amount'], date_str, parsed['type'], parsed['notes'], parsed['category']]

        # append row and reply with formatted message
        try:
            ws.append_row(row)
            reply = format_success_message({
                'amount': parsed['amount'],
                'notes': parsed['notes'],
                'type': parsed['type'],
                'date': parsed['date'],
                'category': parsed['category']
            })
            await update.message.reply_text(reply)
            logger.info('GSHEET: Row append SUCCESS')
        except Exception as e:
            logger.error(f"GSHEET WRITE ERROR: {e}")
            await update.message.reply_text(f"GSHEET ERROR: {e}")

    except Exception as e:
        logger.exception(f"ERROR in log_expense: {e}")
        await update.message.reply_text(f"Bot error: {e}")


async def delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Delete last row from current month sheet
        now = datetime.now(IST)
        ws = get_or_create_monthly_sheet(now)
        last_row = get_last_data_row(ws)
        if not last_row:
            await update.message.reply_text("No entry to delete.")
            return
        # fetch last row values to show
        last_values = ws.row_values(last_row)
        ws.delete_rows(last_row)
        await update.message.reply_text(f"🗑️ Deleted last entry: {last_values}")
    except Exception as e:
        logger.exception(f"ERROR in delete_last: {e}")
        await update.message.reply_text(f"Delete error: {e}")


async def edit_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Usage: /editlast 500 food d  OR launch interactive flow (simple implementation: take rest of message as new entry)
        args_text = ' '.join(context.args) if context.args else ''
        if not args_text:
            await update.message.reply_text("Usage: /editlast <new_entry_text> Example: /editlast 500 milk d")
            return
        parsed = parse_message(args_text)
        if not parsed:
            await update.message.reply_text("Invalid format for edit. Use same formats as /start.")
            return
        now = datetime.now(IST)
        ws = get_or_create_monthly_sheet(now)
        last_row = get_last_data_row(ws)
        if not last_row:
            await update.message.reply_text("No entry to edit.")
            return
        date_str = parsed['date'].strftime('%Y-%m-%d')
        new_row = [parsed['amount'], date_str, parsed['type'], parsed['notes'], parsed['category']]
        # update A{row}:E{row}
        ws.update(f"A{last_row}:E{last_row}", [new_row])
        await update.message.reply_text("✏️ Edited last entry successfully.")
    except Exception as e:
        logger.exception(f"ERROR in edit_last: {e}")
        await update.message.reply_text(f"Edit error: {e}")

# ================= Main =================

def main():
    try:
        # Validate sheets connection early
        get_client_and_spreadsheet()
        logger.info('GSHEET: Connection OK.')

        # Python 3.13+ event loop workaround
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.info('EVENT LOOP: New loop created')

        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('delete', delete_last))
        app.add_handler(CommandHandler('editlast', edit_last))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), log_expense))

        logger.info('BOT: Starting polling now.')
        app.run_polling()

    except Exception as e:
        logger.exception(f"FATAL ERROR IN BOT MAIN: {e}")
        raise


if __name__ == '__main__':
    main()
