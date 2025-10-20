# Helper script to run commands with virtual environment activated
param(
    [Parameter(Mandatory=$true)]
    [string]$Command
)

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Run the command
Invoke-Expression $Command


