# 💸 GPay Expense Bot (Telegram) — Dual-Format Logger 🚀

A **lightweight** Telegram bot 🤖 that logs expenses to **Google Sheets** 📊 using **two** flexible input formats:

1. **Simple format:** `amount notes type` (e.g., `500 Tea d`) 🍵
2. **Tagged format:** `a <amount> n <notes> t <type>` (e.g., `a 1580 n Brush t D`) 🏷️

✅ Entries saved into a **monthly worksheet** named **“Month Year”** (e.g., “August 2025”) 📅
✅ Auto-creates new sheets with **bold & centered headers**, freezes the first row, and appends rows with an **IST date** (YYYY-MM-DD) 🕒

---

## ✨ Key Features

🎉 **Dual Input Support**
- *Simple:* `500 Tea d` → ₹500 **Debit** for Tea 🍵
- *Tagged:* `a 1580 n Brush t D` → ₹1,580 **Debit** for Brush 🖌️

🗂️ **Monthly Sheet Management**
- Auto-creates monthly sheets (e.g., “August 2025”) 📁
- Applies headers & formatting only once per month 🎨

🧹 **Input Cleaning & Validation**
- 💰 **Amount**: Commas & decimals handled
- 📝 **Notes**: Removes special chars, collapses spaces
- 🏷️ **Category**: Auto-assigns based on keywords 🎯

🔗 **Google Sheets API** Integration 🤝
🖋️ **Markdown-Formatted** Telegram replies 📨

---

## 📑 Saved Columns

| Column    | Description                                                     |
|-----------|-----------------------------------------------------------------|
| 💰 Amount | Numeric value (₹)                                               |
| 📅 Date   | YYYY-MM-DD, Asia/Kolkata                                        |
| 🔄 Type   | **DEBIT** or **CREDIT**                                         |
| 📝 Notes  | Description of expense                                         |
| 🏷️ Category | Auto-assigned based on notes                                     |

---

## 📋 Supported Message Formats

| Format  | Example                  | Parsed As                              |
|---------|--------------------------|-----------------------------------------|
| Simple  | `500 Tea d`              | Amount=500, Notes=Tea, Type=Debit      |
| Tagged  | `a 1580 n Brush t d`     | Amount=1580, Notes=Brush, Type=Debit   |

> **Type Tags:** `d`/`D` = **Debit** 🔻, `c`/`C` = **Credit** 🔺

✋ Send `/start` for detailed usage instructions 📖

---

## ⚙️ Requirements

- 🐍 **Python 3.10+**
- 🤖 **Telegram Bot Token**
- 📊 **Google Sheets Spreadsheet ID**
- 🔑 **Google Service Account JSON Key**

---

## 🚀 Setup Guide

1️⃣ **Clone & Enter Project**
```bash
git clone <repo-url>
cd gpay_expense_bot
```

2️⃣ **Create & Activate venv**
```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux 🐧
# .venv\\Scripts\\activate  # Windows 💻
```

3️⃣ **Install Dependencies**
```bash
pip install -r requirements.txt
```

4️⃣ **Create `.env`**
```ini
TELEGRAM_BOT_TOKEN=your_bot_token
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

5️⃣ **Run the Bot**
```bash
export TZ=Asia/Kolkata  # ensure IST timezone 🕒
python bot.py
```

---

## 💡 Usage Examples

### Simple format:
```text
500 Lunch d 🍽️
1200 Salary c 💼
```

### Tagged format:
```text
a 250 n Coffee t d ☕
a 3000 n Freelance t c 🖥️
```

The bot replies:
```
✅ **Saved!**
💰 Amount: ₹250
📝 Notes: Coffee
📅 Date: 2025-08-30
🔄 Type: DEBIT
🏷️ Category: Entertainment
```
And appends a row to the sheet.

---

## 🛠️ Troubleshooting

- ❌ **Missing Bot Token** → Add `TELEGRAM_BOT_TOKEN` in `.env`
- ❌ **Key File Not Found** → Verify `service_account.json` path in `.env`
- ❌ **Permission Denied** → Share sheet with service account email ✉️

---

## 🔒 Security

- 🚫 Don’t commit `.env` or JSON key
- 🔒 Limit service account scopes to necessary 

---

## 🔜 Roadmap

- 🔄 Switch/override target month command
- 📊 Monthly summary/exports
- ⚠️ Validation prompts for missing tags

---

## 📜 License

MIT © 2025 — Use & modify freely ✌️
