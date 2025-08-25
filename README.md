# 💸 GPay Expense Bot (Telegram) — Tag-Based Logger

A lightweight Telegram bot 🤖 that logs expenses to **Google Sheets** 📊 using a compact, human-friendly tagged message.

```text
a <amount> n <notes> t <type>
```
👉 Example: `a 1580 n Brush t D`

✅ Entries are saved into a monthly worksheet named **“Month Year”** (e.g., “August 2025”).  
✅ The bot auto-creates the sheet, writes bold, centered headers, freezes the first row, and appends rows with an **IST date (no time)**.

---

## ✨ Features

- 💬 Simple tagged message format: `a <amount> n <notes> t <type>`  
- 📅 Auto-creates monthly sheets with headers (**Amount | Date | Type | Notes**)  
- 🧹 Cleans input (amount formatting, notes sanitization)  
- 🕒 Saves **date-only timestamps (IST)**  
- ✅ Works with **Google Sheets API + Telegram Bot API**

---

## 📝 Message format

| Tag | Meaning | Example | Saved As |
|-----|---------|---------|----------|
| 🏷 `a <amount>` | 💰 Amount | `a 1580` | **1,580** |
| 🏷 `n <notes>` | 📝 Notes | `n Brush` | **Brush** |
| 🏷 `t <type>` | 🔄 Type (D = Debit, C = Credit) | `t D` | **DEBIT** |

🔹 Tags are **case-insensitive** and may include spaces after the tag.  
Examples:
- `a 1580 n Brush t D`
- `A 1,250 N fuel T c`
- `a 500 n Tea t d`

---

## 📑 Saved columns

Each row in the monthly sheet (e.g., **August 2025**) contains:  

- 💰 **Amount**  
- 📅 **Date (YYYY-MM-DD, IST)**  
- 🔄 **Type (CREDIT or DEBIT)**  
- 📝 **Notes**  

📌 Header row: **Amount | Date | Type | Notes**  
- Styled bold, centered, first row frozen.

---

## ⚙️ Requirements

- 🤖 Telegram Bot Token  
- 📊 Google Sheet (Spreadsheet ID)  
- 🔑 Google Cloud Service Account JSON key  
- 🐍 Python 3.10+ (tested with 3.10 / 3.12)

---

## 🚀 Setup

1️⃣ **Create a Telegram bot**  
- Talk to @BotFather → `/newbot` → copy the bot token.

2️⃣ **Create or choose a Google Sheet**  
- Copy the **Spreadsheet ID** from its URL.

3️⃣ **Google Cloud service account + key**  
- Enable **Google Sheets API** and **Google Drive API**.  
- Create service account → download JSON key (`service_account.json`).  
- Share Google Sheet with the service account email as **Editor**.

4️⃣ **Local project setup**
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scriptsctivate
pip install -r requirements.txt
```

📄 Create a `.env` file:
```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

5️⃣ **Run the bot**
```bash
export TZ=Asia/Kolkata   # optional (for consistency)
python bot.py
```

---

## 💡 Usage

Send a tagged message to the bot:
```text
a <amount> n <notes> t <type>
```

The bot replies with:
- ✅ Saved
- 💰 Amount
- 📝 Notes
- 📅 Date (IST)
- 🔄 Type

👉 Row is appended to the correct **“Month Year”** worksheet.

---

## 🧹 Cleaning & Validation

- 💰 **Amount**
  - Digits, commas, decimals allowed.
  - “1,580” → “1,580”
  - “1580” → “1,580”
  - “1,580.00” → “1,580”
  - “1580.5” → “1,580.50”

- 📝 **Notes**
  - Letters, digits, spaces only.
  - Repeated spaces collapsed.
  - Other symbols removed.

- 🔄 **Type**
  - `t D / t d` → **DEBIT**
  - `t C / t c` → **CREDIT**
  - Anything else → `-`

---

## 📅 Behavior

- 🗂 Monthly sheet naming: **“Month Year”** (e.g., *August 2025*)
- 📄 Auto sheet creation: headers + formatting applied once per month
- 🕒 Timestamps: IST, date-only (`YYYY-MM-DD`)

---

## 🛠 Troubleshooting

- ❌ **Permission denied** → Share Google Sheet with service account email.
- ❌ **Missing key file** → Ensure correct path in `.env`.
- ❌ **Missing bot token** → Add `TELEGRAM_BOT_TOKEN` in `.env`.

---

## 🔐 Security

- 🚫 Do **not** commit your service account JSON or bot token.
- 🔒 Restrict service account to only needed APIs/docs.

---

## 🛤 Roadmap

- 🔄 Command to switch/override target month
- 📊 Monthly summaries/exports
- ⚠️ Validation prompts for missing tags

---

## 📜 License

🆓 MIT — Use and modify freely.