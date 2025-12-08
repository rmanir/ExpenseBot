import os
import logging
import re
from datetime import datetime
import asyncio
import base64
import json
import pytz
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from dotenv import load_dotenv

load_dotenv()

# Stabilize timezone
os.environ.setdefault("TZ", "Asia/Kolkata")

# Enhanced logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Load environment variables with error checking
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64")

# File location to write decoded JSON
SERVICE_ACCOUNT_FILE = "service_account.json"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Error: TELEGRAM_BOT_TOKEN is not set.")
if not SPREADSHEET_ID:
    raise RuntimeError("Error: GOOGLE_SHEETS_SPREADSHEET_ID is not set.")
if not SERVICE_ACCOUNT_B64:
    raise RuntimeError("Error: GOOGLE_SERVICE_ACCOUNT_B64 (base64 key) is not set.")


# ---------- Base64 Decode & Write JSON ----------
def write_service_account_file():
    """Decode Base64 service account JSON and write to file safely."""
    try:
        decoded = base64.b64decode(SERVICE_ACCOUNT_B64)
        data = json.loads(decoded)
        with open(SERVICE_ACCOUNT_FILE, "w") as f:
            json.dump(data, f)
        logging.info("Service account JSON written successfully.")
    except Exception as e:
        logging.error("Failed to decode Base64 service account key.")
        raise e


# Timezone IST
IST = pytz.timezone("Asia/Kolkata")


# --- Category Mapper ---
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
    "car": "Travel",
    "ef": "Emergency Fund",
}

# --- Category Budget ---
CATEGORY_TARGETS = {
    "Rent": 17000,
    "Grocery": 10000,
    "Travel": 8000,
    "Entertainment": 10000,
    "Investment": 25000,
    "Petrol": 2000,
    "Gas & Water": 1000,
    "Medicine": 3000,
    "EB & EC": 3000,
    "Others": 15000,
    "Withdrawal": 0,
    "Emergency Fund": 20000,
}


def categorize(notes: str) -> str:
    """Categorize transaction based on notes content."""
    notes_lower = notes.lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in notes_lower:
            return category
    return "Others"


# ---------- Google Sheets ----------
def get_client_and_spreadsheet():
    """Initialize Google Sheets client using Base64-decoded JSON."""
    write_service_account_file()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return client, spreadsheet


def ensure_headers_and_format(sheet):
    """Ensure headers exist, are properly formatted, and first row is frozen."""
    headers = ["Amount", "Date", "Type", "Notes", "Category"]
    try:
        first_row = sheet.row_values(1)
    except Exception:
        first_row = []

    # Update headers if they don't match
    if [h.strip() for h in (first_row or [])] != headers:
        sheet.update("A1:E1", [headers])

    # Format headers: bold + center
    fmt = {
        "textFormat": {"bold": True},
        "horizontalAlignment": "CENTER",
    }
    sheet.format("A1:E1", fmt)

    # Freeze first row
    try:
        sheet.freeze(rows=1)
    except Exception:
        pass


def get_or_create_monthly_sheet(date_obj=None):
    """Get or create monthly sheet with proper formatting."""
    target_date = date_obj if date_obj else datetime.now(IST)
    month_year = target_date.strftime("%B %Y")

    try:
        _, spreadsheet = get_client_and_spreadsheet()
        sheet = spreadsheet.worksheet(month_year)
        ensure_headers_and_format(sheet)
        return sheet
    except gspread.exceptions.WorksheetNotFound:
        _, spreadsheet = get_client_and_spreadsheet()
        sheet = spreadsheet.add_worksheet(title=month_year, rows=1000, cols=5)
        headers = ["Amount", "Date", "Type", "Notes", "Category"]
        sheet.append_row(headers)

        # Format headers
        fmt = {
            "textFormat": {"bold": True},
            "horizontalAlignment": "CENTER",
        }
        sheet.format("A1:E1", fmt)
        sheet.freeze(rows=1)
        return sheet


def get_or_create_budget_sheet(year):
    """Ensure 'Budget <year>' sheet exists with header and target row."""
    sheet_name = f"Budget {year}"
    try:
        _, spreadsheet = get_client_and_spreadsheet()
        sheet = spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        _, spreadsheet = get_client_and_spreadsheet()
        sheet = spreadsheet.add_worksheet(
            title=sheet_name, rows=100, cols=len(CATEGORY_TARGETS) + 1
        )

        # Headers
        headers = ["Month"] + list(CATEGORY_TARGETS.keys())
        sheet.append_row(headers)

        # Target row
        targets = ["Target"] + [CATEGORY_TARGETS[cat] for cat in CATEGORY_TARGETS]
        sheet.append_row(targets)

        # Formatting
        fmt = {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}
        sheet.format("A1:Z1", fmt)
        sheet.freeze(rows=2)

    return sheet


# --- Message Parser (Supporting both formats) ---
def parse_simple_format(text: str):
    """Parse simple format: amount notes type (e.g. '500 Tea d')."""
    parts = text.strip().split()
    if len(parts) < 2:
        return None, None, None, None, None

    # First part = amount
    try:
        amount = float(parts[0].replace(",", ""))
    except ValueError:
        return None, None, None, None, None

    # Last part = type
    tx_type = parts[-1].lower()
    if tx_type not in ["d", "c"]:
        return None, None, None, None, None

    # Middle parts = notes
    notes = " ".join(parts[1:-1]).strip()

    # Normalize
    tx_type = "Debit" if tx_type == "d" else "Credit"
    category = categorize(notes)

    # Return None for date, as this format doesn't support it
    return amount, notes, tx_type, category, None


def parse_tagged_format(text: str):
    """Parse tagged format: a <amount> n <notes> t <type> d <date>."""

    TAG_A = re.compile(r"(?<!\S)[aA]\s*([0-9][0-9,\.]*?)\b")
    TAG_T = re.compile(r"(?<!\S)[tT]\s*([cCdD])\b")
    TAG_N = re.compile(r"(?<!\S)[nN]\s*(.+?)(?=\s+[aAnNtTdD]\b|$)")
    TAG_D = re.compile(
        r"(?<!\S)[dD]\s*(\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?)\b"
    )  # Date Tag

    amt_match = TAG_A.search(text)
    type_match = TAG_T.search(text)
    note_match = TAG_N.search(text)
    date_match = TAG_D.search(text)

    if not amt_match or not type_match:
        return None, None, None, None, None

    try:
        amount = float(amt_match.group(1).replace(",", ""))
    except ValueError:
        return None, None, None, None, None

    tx_type = type_match.group(1).upper()
    tx_type = "Credit" if tx_type == "C" else "Debit"

    notes = note_match.group(1).strip() if note_match else ""
    notes = re.sub(r"[^A-Za-z0-9 ]", " ", notes)
    notes = re.sub(r"\s+", " ", notes).strip() or "Transaction"

    category = categorize(notes)

    # Date parsing
    manual_date = None
    if date_match:
        date_str = date_match.group(1).replace("/", "-").replace(".", "-")
        try:
            # Try DD-MM-YYYY or DD-MM-YY
            if len(date_str.split("-")[-1]) == 4:
                manual_date = datetime.strptime(date_str, "%d-%m-%Y")
            else:
                manual_date = datetime.strptime(date_str, "%d-%m-%y")
        except ValueError:
            try:
                # Try DD-MM, assume current year
                manual_date = datetime.strptime(date_str, "%d-%m").replace(
                    year=datetime.now().year
                )
            except ValueError:
                manual_date = None

    return amount, notes, tx_type, category, manual_date


def parse_message(text: str):
    """Parse message in either format - tagged or simple."""
    if re.search(r"[aA]\s*\d", text) and re.search(r"[tT]\s*[cdCD]", text):
        return parse_tagged_format(text)
    return parse_simple_format(text)


# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    msg = (
        "🤖 **Expense Tracker Bot**\n\n"
        "📝 **Two formats supported:**\n\n"
        "**1. Simple format (for today's date):**\n"
        "`amount notes type`\n"
        "Example: `500 Tea d`\n\n"
        "**2. Tagged format (with optional date):**\n"
        "`a <amount> n <notes> t <type> d <date>`\n"
        "Example: `a 1580 n Brush t d d 28-08-2025`\n\n"
        "**Tags & Types:**\n"
        "• `a` - Amount\n"
        "• `n` - Notes\n"
        "• `t` - Type (`d`/`D` for Debit, `c`/`C` for Credit)\n"
        "• `d` - **Date (Optional)**. Accepts `dd-mm-yyyy`, `dd-mm-yy`, or `dd-mm`.\n\n"
        "Entries are saved in monthly sheets. Categories are auto-assigned! 🎯"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def log_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle expense logging messages."""
    try:
        message_text = update.message.text
        amount, notes, tx_type, category, manual_date = parse_message(message_text)

        if not amount or not tx_type:
            await update.message.reply_text(
                "❌ **Invalid format**\n\n"
                "**Use either:**\n"
                "• `500 Tea d` (simple)\n"
                "• `a 500 n Tea t d` (tagged)\n\n"
                "Send /start for more details",
                parse_mode="Markdown",
            )
            return

        # Use manual date if provided, otherwise current date
        if manual_date:
            date_to_log = IST.localize(manual_date)
        else:
            date_to_log = datetime.now(IST)

        date_str = date_to_log.strftime("%Y-%m-%d")

        # Save to monthly sheet
        sheet = get_or_create_monthly_sheet(date_to_log)
        sheet.append_row([amount, date_str, tx_type, notes, category])

        # --- BUDGET FEATURE: Update budget sheet ---
        budget_year = date_to_log.year
        budget_sheet = get_or_create_budget_sheet(budget_year)
        month_name = date_to_log.strftime("%B")

        budget_rows = budget_sheet.get_all_values()
        header_row = budget_rows[0]
        existing_months = [row[0] for row in budget_rows[2:]]  # skip 2 header rows

        col_map = {cat: idx for idx, cat in enumerate(header_row)}
        col_index = col_map.get(category, col_map.get("Others", 1))

        if month_name in existing_months:
            row_idx = existing_months.index(month_name) + 3  # +3 to skip 2 header rows
            current_value = budget_sheet.cell(row_idx, col_index + 1).value or "0"
            try:
                new_value = float(current_value) + amount
            except ValueError:
                new_value = amount
            budget_sheet.update_cell(row_idx, col_index + 1, new_value)
        else:
            row = [""] * len(header_row)
            row[0] = month_name
            row[col_index] = amount
            budget_sheet.append_row(row)

        # Format amount for display
        if float(amount).is_integer():
            amount_display = f"{int(amount):,}"
        else:
            amount_display = f"{amount:,.2f}"

        reply = (
            f"✅ **Saved Successfully!**\n\n"
            f"💰 **Amount:** ₹{amount_display}\n"
            f"📝 **Notes:** {notes}\n"
            f"📅 **Date:** {date_str}\n"
            f"📂 **Category:** {category}\n"
            f"🔖 **Type:** {tx_type}"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error processing expense: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ **Error:** {str(e)}", parse_mode="Markdown"
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages."""
    await update.message.reply_text(
        "📷 **Photo received!**\n\n"
        "Please send expense data as text:\n"
        "• `500 Tea d` (simple)\n"
        "• `a 500 n Tea t d` (tagged)\n\n"
        "Send /start for help",
        parse_mode="Markdown",
    )


# --- Time-limited bot runner for GitHub Actions ---
async def run_bot_for(duration_seconds: int = 900):
    """
    Run the Telegram bot for a fixed duration (default: 900s = 15 minutes),
    then stop it cleanly.
    """
    try:
        # Test Google Sheets connection at startup
        get_client_and_spreadsheet()
        logging.info("✅ Google Sheets connection successful")

        # Build application
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(
            MessageHandler(filters.TEXT & (~filters.COMMAND), log_expense)
        )
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        logging.info("🤖 Bot starting (time-limited run)...")

        async with app:
            await app.start()
            await app.start_polling()

            logging.info(f"⏱ Running bot for {duration_seconds} seconds...")
            try:
                await asyncio.sleep(duration_seconds)
            finally:
                logging.info("🛑 Stopping bot after time limit...")
                await app.stop()

        logging.info("✅ Bot stopped cleanly")

    except Exception as e:
        logging.error(f"❌ Failed to run bot: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # 15 minutes = 900 seconds
    asyncio.run(run_bot_for(900))