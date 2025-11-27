Write-Host "=== ExpenseBot Bot Launcher ===" -ForegroundColor Cyan

# Step 1: Check venv exists
if (!(Test-Path ".venv")) {
    Write-Host "ERROR: Virtual environment (.venv) not found. Run setup.ps1 first." -ForegroundColor Red
    exit
}

# Step 2: Activate venv
Write-Host "Activating virtual environment..."
& .\.venv\Scripts\Activate

Write-Host "Python version:"
python --version

# Step 3: Validate bot dependencies
$required = @("python-telegram-bot", "gspread", "google.auth", "apscheduler")

foreach ($pkg in $required) {
    try {
        python -c "import $pkg" 2>$null
        Write-Host "OK: $pkg" -ForegroundColor Green
    }
    catch {
        Write-Host "Missing dependency: $pkg — installing..." -ForegroundColor Yellow
        pip install $pkg
    }
}

# Step 4: Run bot with auto-restart
Write-Host "`nStarting bot..." -ForegroundColor Cyan

while ($true) {
    try {
        python bot.py
        Write-Host "`nBot stopped. Restarting in 3 seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
    catch {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        Start-Sleep -Seconds 3
    }
}
