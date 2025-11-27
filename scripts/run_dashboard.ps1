Write-Host "=== ExpenseBot Dashboard Launcher ===" -ForegroundColor Cyan

# Step 1: Check if venv exists
if (!(Test-Path ".venv")) {
    Write-Host "ERROR: .venv not found. Run setup.ps1 first." -ForegroundColor Red
    exit
}

# Step 2: Activate venv
Write-Host "Activating virtual environment..."
& .\.venv\Scripts\Activate

Write-Host "Python version:"
python --version

# Step 3: Validate Streamlit installation
try {
    python -c "import streamlit"
    Write-Host "Streamlit found." -ForegroundColor Green
}
catch {
    Write-Host "Streamlit is NOT installed. Installing now..." -ForegroundColor Yellow
    pip install streamlit
}

# Step 4: Run dashboard
Write-Host "`nStarting dashboard..." -ForegroundColor Cyan

# Loop: Auto restart on crash
while ($true) {
    try {
        streamlit run dashboard.py
        Write-Host "`nDashboard stopped. Press Ctrl+C to exit or restarting in 3 seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
    catch {
        Write-Host "An error occurred: $($_.Exception.Message)" -ForegroundColor Red
        Start-Sleep -Seconds 3
    }
}
