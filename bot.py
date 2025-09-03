import os
import logging
import re
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from dotenv import load_dotenv
load_dotenv()

# Stabilize timezone
os.environ.setdefault("TZ", "Asia/Kolkata")

# Enhanced logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Load environment variables with error checking
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Error: TELEGRAM_BOT_TOKEN is not set")
if not SPREADSHEET_ID:
    raise RuntimeError("Error: GOOGLE_SHEETS_SPREADSHEET_ID is not set")

# Check service account file exists
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    raise RuntimeError(f"Service account JSON not found at: {SERVICE_ACCOUNT_FILE}")

# Timezone IST
IST = pytz.timezone("Asia/Kolkata")

# --- Category Mapper ---
CATEGORY_MAP = {
    "rent": "Rent",
    "stock": "Investment",
    "insurance": "Investment",
    "gold": "Investment",
    "eb": "EB & EC",
    "ec": "EB & EC",
    "internet bill": "EB & EC",
    "withdrawal": "Withdrawal",
    "petrol": "Petrol",
    "bus": "Travel",
    "irctc": "Travel",
    "carpetrol": "Travel",
    "cpetrol": "Travel",
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
    "flower":"Grocery",
    "income": "Income",
    "salary": "Income",
    "investment": "Investment",
    "milk": "Grocery",
    "tea": "Entertainment",
    "icecream": "Entertainment"
}

def categorize(notes: str) -> str:
    """Categorize transaction based on notes content."""
    notes_lower = notes.lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in notes_lower:
            return category
    return "Others"

# --- Google Sheets Setup ---
def get_client_and_spreadsheet():
    """Initialize Google Sheets client and spreadsheet."""
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
        "horizontalAlignment": "CENTER"
    }
    sheet.format("A1:E1", fmt)
    
    # Freeze first row
    try:
        sheet.freeze(rows=1)
    except Exception:
        pass

def get_or_create_monthly_sheet(date_obj=None):
    """Get or create monthly sheet with proper formatting."""
    # Use provided date_obj or default to now()
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
            "horizontalAlignment": "CENTER"
        }
        sheet.format("A1:E1", fmt)
        sheet.freeze(rows=1)
        return sheet

# --- Message Parser (Supporting both formats) ---
def parse_simple_format(text: str):
    """Parse simple format: amount notes type (e.g., '500 Tea d')"""
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
    """Parse tagged format: a <amount> n <notes> t <type> d <date>"""
    # Regex patterns for tagged format
    TAG_A = re.compile(r"(?<!\S)[aA]\s*([0-9][0-9,\.]*?)\b")
    TAG_T = re.compile(r"(?<!\S)[tT]\s*([cCdD])\b")
    TAG_N = re.compile(r"(?<!\S)[nN]\s*(.+?)(?=\s+[aAnNtTdD]\b|$)")
    TAG_D = re.compile(r"(?<!\S)[dD]\s*(\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?)\b") # Date Tag

    amt_match = TAG_A.search(text)
    type_match = TAG_T.search(text)
    note_match = TAG_N.search(text)
    date_match = TAG_D.search(text) # Search for date
    
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
    
    # --- New Date Parsing Logic ---
    manual_date = None
    if date_match:
        date_str = date_match.group(1).replace("/", "-").replace(".", "-")
        try:
            # Try parsing with year: DD-MM-YYYY or DD-MM-YY
            if len(date_str.split('-')[-1]) == 4:
                manual_date = datetime.strptime(date_str, "%d-%m-%Y")
            else:
                manual_date = datetime.strptime(date_str, "%d-%m-%y")
        except ValueError:
            try:
                # Try parsing without year: DD-MM, assume current year
                manual_date = datetime.strptime(date_str, "%d-%m").replace(year=datetime.now().year)
            except ValueError:
                manual_date = None # Invalid date format
    
    return amount, notes, tx_type, category, manual_date

def parse_message(text: str):
    """Parse message in either format - tagged or simple."""
    # Try tagged format first (a ... n ... t ...)
    # The regex now checks for 'd' (date) as a possible tag
    if re.search(r"[aA]\s*\d", text) and re.search(r"[tT]\s*[cdCD]", text):
        return parse_tagged_format(text)
    
    # Fall back to simple format (amount notes type)
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
        # The parser now returns a 5th value: manual_date
        amount, notes, tx_type, category, manual_date = parse_message(message_text)
        
        if not amount or not tx_type:
            await update.message.reply_text(
                "❌ **Invalid format**\n\n"
                "**Use either:**\n"
                "• `500 Tea d` (simple)\n"
                "• `a 500 n Tea t d` (tagged)\n\n"
                "Send /start for more details",
                parse_mode="Markdown"
            )
            return

        # --- Use manual date if provided, otherwise use current date ---
        if manual_date:
            # Add timezone info to the manually parsed date
            date_to_log = IST.localize(manual_date)
        else:
            date_to_log = datetime.now(IST)
        
        date_str = date_to_log.strftime("%Y-%m-%d")
        
        # Save to Google Sheets, passing the date to get the correct sheet
        sheet = get_or_create_monthly_sheet(date_to_log)
        sheet.append_row([amount, date_str, tx_type, notes, category])
        
        # Format amount for display
        amount_display = f"{amount:,.2f}" if amount != int(amount) else f"{int(amount):,}"
        
        # Send confirmation
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
        logging.error(f"Error processing expense: {e}")
        await update.message.reply_text(f"❌ **Error:** {str(e)}", parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages."""
    await update.message.reply_text(
        "📷 **Photo received!**\n\n"
        "Please send expense data as text:\n"
        "• `500 Tea d` (simple)\n"
        "• `a 500 n Tea t d` (tagged)\n\n"
        "Send /start for help"
    )

# --- Main ---
def main():
    """Main function to run the bot."""
    try:
        # Test Google Sheets connection at startup
        get_client_and_spreadsheet()
        logging.info("✅ Google Sheets connection successful")
        
        # Build application
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), log_expense))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        logging.info("🤖 Bot starting...")
        app.run_polling()
        
    except Exception as e:
        logging.error(f"❌ Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    main()