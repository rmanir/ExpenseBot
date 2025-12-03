# ================================
#  ExpenseBot – One-click Local Runner
#  For Windows PowerShell
# ================================

Write-Host "=== ExpenseBot Local Setup ===" -ForegroundColor Cyan

# -------- Step 1: Check Python Installation --------
$python = Get-Command python -ErrorAction SilentlyContinue

if (-not $python) {
    Write-Host "❌ Python is not installed (expected Python 3.12)" -ForegroundColor Red
    Write-Host "Download here: https://www.python.org/downloads/release/python-3120/"
    exit
}

# -------- Step 2: Create Virtual Environment --------
Write-Host "`nCreating virtual environment (.venv)..." -ForegroundColor Yellow
python -m venv .venv

if (-not (Test-Path ".\.venv")) {
    Write-Host "❌ Failed to create virtual environment" -ForegroundColor Red
    exit
}

Write-Host "✔ Virtual environment created" -ForegroundColor Green


# -------- Step 3: Activate Virtual Environment --------
Write-Host "`nActivating .venv..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

if (-not $env:VIRTUAL_ENV) {
    Write-Host "❌ Failed to activate virtual environment" -ForegroundColor Red
    exit
}

Write-Host "✔ Virtual environment activated" -ForegroundColor Green


# -------- Step 4: Install Dependencies --------
$reqFile = ".\bot\requirements_bot.txt"

if (-not (Test-Path $reqFile)) {
    Write-Host "❌ requirements_bot.txt not found in /bot folder" -ForegroundColor Red
    exit
}

Write-Host "`nInstalling dependencies..." -ForegroundColor Yellow
pip install --upgrade pip
pip install -r $reqFile

Write-Host "✔ Dependencies installed" -ForegroundColor Green


# -------- Step 5: Check .env --------
$envFile = ".\.env"

if (-not (Test-Path $envFile)) {
    Write-Host "❌ .env file not found!" -ForegroundColor Red
    Write-Host "Create .env with:"
    Write-Host "BOT_TOKEN=xxxx"
    Write-Host "GOOGLE_SERVICE_ACCOUNT_BASE64=xxxx"
    Write-Host "GOOGLE_SHEETS_SPREADSHEET_ID=xxxx"
    exit
}

Write-Host "✔ .env file found" -ForegroundColor Green


# -------- Step 6: Run health server in background --------
Write-Host "`nStarting health server on port 8080..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoProfile -WindowStyle Hidden -Command `".\.venv\Scripts\python.exe bot\health.py`""

Write-Host "✔ health.py running in background" -ForegroundColor Green


# -------- Step 7: Start bot --------
Write-Host "`n🚀 Starting ExpenseBot..." -ForegroundColor Cyan
python bot\bot.py
