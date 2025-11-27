Write-Host "=== ExpenseBot Auto Setup Script ===" -ForegroundColor Cyan

# Step 1: Check Python 3.12 availability
Write-Host "`nChecking Python 3.12 installation..."
$python = & py -3.12 --version 2>$null

if (!$python) {
    Write-Host "Python 3.12 is NOT installed. Install it first." -ForegroundColor Red
    exit
}

Write-Host "Python 3.12 is installed: $python" -ForegroundColor Green


# Step 2: Create virtual environment
Write-Host "`nCreating virtual environment .venv ..."
& py -3.12 -m venv .venv

if (!(Test-Path ".venv")) {
    Write-Host "Failed to create venv." -ForegroundColor Red
    exit
}

Write-Host "Virtual environment created." -ForegroundColor Green


# Step 3: Activate venv
Write-Host "`nActivating venv..."
& .\.venv\Scripts\Activate

Write-Host "Venv Activated. Python version:"
python --version


# Step 4: Install dependencies
Write-Host "`nInstalling dependencies from requirements.txt ..."
pip install --upgrade pip
pip install -r requirements.txt

Write-Host "`nDependency installation completed!" -ForegroundColor Green


# Step 5: Validation
Write-Host "`nValidating key packages..."

$packages = @("numpy", "pandas", "streamlit", "python-telegram-bot")

foreach ($pkg in $packages) {
    try {
        python -c "import $pkg"
        Write-Host "OK: $pkg" -ForegroundColor Green
    } catch {
        Write-Host "FAILED: $pkg" -ForegroundColor Red
    }
}

Write-Host "`nValidation complete."


# Step 6: Start bot
Write-Host "`nStarting bot.py ..." -ForegroundColor Cyan
python bot.py