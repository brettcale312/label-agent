<#
reset_env.ps1
--------------
Quick cleanup utility for Label-Agent development.

🧹 Kills any hung terminals, Python servers, or Node.js builds.
🧠 Safe to run anytime things freeze or hang in VS Code / Cursor.
#>

Write-Host "🚨 Resetting development environment..." -ForegroundColor Yellow

# Kill PowerShell, Node, and Python processes
$processes = @("powershell.exe", "node.exe", "python.exe", "uvicorn.exe")
foreach ($p in $processes) {
    try {
        taskkill /IM $p /F /T | Out-Null
        Write-Host "✅ Killed $p" -ForegroundColor Red
    } catch {
        Write-Host "ℹ️ $p not running." -ForegroundColor Gray
    }
}

# Optional: also clean any orphaned Vite or FastAPI ports
$ports = @(5173, 8000)
foreach ($port in $ports) {
    try {
        $pid = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess
        if ($pid) {
            Stop-Process -Id $pid -Force
            Write-Host "⚡ Freed port $port (PID $pid)" -ForegroundColor Magenta
        }
    } catch {
        Write-Host "ℹ️ Port $port already free." -ForegroundColor Gray
    }
}

Write-Host "`n🎯 Environment reset complete! Open a new PowerShell or VS Code terminal." -ForegroundColor Green
Start-Sleep -Seconds 2
