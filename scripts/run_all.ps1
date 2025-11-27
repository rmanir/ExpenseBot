Write-Host "=== ExpenseBot Full Launcher (Bot + Dashboard) ===" -ForegroundColor Cyan

# Check venv
if (!(Test-Path ".venv")) {
    Write-Host "ERROR: .venv not found. Run setup.ps1 first." -ForegroundColor Red
    exit
}

# Activate venv
& .\.venv\Scripts\Activate
Write-Host "Python version:"
python --version

# Launch bot in background
Write-Host "`nLaunching bot in background..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$PWD\run_bot_background.ps1`""

# Launch dashboard
Write-Host "`nLaunching dashboard..." -ForegroundColor Cyan
streamlit run dashboard.py
