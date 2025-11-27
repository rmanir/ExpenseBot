Write-Host "Starting bot in background mode..." -ForegroundColor Green

& .\.venv\Scripts\Activate

while ($true) {
    try {
        python bot.py
        Start-Sleep -Seconds 2
    }
    catch {
        Write-Host "Bot crashed: $($_.Exception.Message)" -ForegroundColor Red
        Start-Sleep -Seconds 2
    }
}
