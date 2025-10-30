<#
run_with_venv.ps1
-----------------
Runs any command inside the project's virtual environment.
Automatically detects whether you’re in the backend or frontend folder.
Usage:
  .\run_with_venv.ps1 "uvicorn app.main:app --reload"
  .\run_with_venv.ps1 "npm run dev"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Command
)

# Determine where the script is running from
$currentDir = Get-Location
$parentDir = Split-Path $currentDir -Parent

# Figure out where the venv lives
if (Test-Path "$currentDir\.venv\Scripts\Activate.ps1") {
    $venvPath = "$currentDir\.venv\Scripts\Activate.ps1"
} elseif (Test-Path "$parentDir\.venv\Scripts\Activate.ps1") {
    $venvPath = "$parentDir\.venv\Scripts\Activate.ps1"
} else {
    Write-Host "⚠️ Could not find virtual environment (.venv) in current or parent folder."
    exit 1
}

# Activate venv
& $venvPath
Write-Host "✅ Activated virtual environment at $venvPath"

# Move to correct working directory for npm or uvicorn
if (Test-Path "$currentDir\package.json") {
    Write-Host "📁 Detected frontend environment."
    Set-Location $currentDir
} else {
    Write-Host "📁 Detected backend environment."
    Set-Location $parentDir
}

# Run the command
Write-Host "🚀 Running command: $Command"
Invoke-Expression $Command


