# One-time setup on Windows (PowerShell 5.1+). Installs everything needed to run the NeonByte agents.
#   powershell -ExecutionPolicy Bypass -File local\setup.ps1
# 1. installs uv (https://docs.astral.sh/uv/) if missing  2. downloads a private Python 3.13
# 3. creates .venv and installs local\requirements.txt    4. checks for AWS credentials
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing uv (official installer from astral.sh)"
    $env:UV_NO_MODIFY_PATH = "1"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
Write-Host "==> $(uv --version)"
Write-Host "==> Python 3.13 + virtualenv (.venv)"
uv python install 3.13 | Out-Null
uv venv --allow-existing --python 3.13 .venv | Out-Null
Write-Host "==> Installing dependencies (first run takes a few minutes)"
$env:VIRTUAL_ENV = "$Root\.venv"
uv pip install --quiet -r local\requirements.txt

$py = "$Root\.venv\Scripts\python.exe"
& $py -c "import boto3,sys; sys.exit(0 if boto3.Session().get_credentials() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "==> AWS credentials found" }
else { Write-Host "==> No AWS credentials found: run 'aws sso login --profile <p>' and set `$env:AWS_PROFILE, or set access keys." }
Write-Host ""
Write-Host "Setup complete. Start an agent:   powershell -File local\run-agent.ps1 orchestrator"
Write-Host "Then in another terminal:         .venv\Scripts\python local\ask.py `"Recommend earbuds under `$300`""
