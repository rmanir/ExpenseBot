#!/bin/bash

# Go to project directory
cd /Users/trane1/Downloads/gpay_expense_bot || exit

# Activate virtual environment
source .venv/bin/activate

# Export service account environment variable
export GOOGLE_SERVICE_ACCOUNT_FILE=/Users/trane1/Downloads/gpay_expense_bot/service_account.json

# Run the bot
python bot.py
