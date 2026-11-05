# One-time setup on Windows (PowerShell 5.1+). Installs everything needed to run the NeonByte agents.
#   powershell -ExecutionPolicy Bypass -File local\setup.ps1
# 1. uses uv (installs it with pip if missing)            2. uv downloads a private Python 3.13
# 3. creates .venv and installs local\requirements.txt    4. checks for AWS credentials
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # Installed as a Python package from your configured index, never by running a downloaded script.
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }  # PowerShell 5.1 has no ?? operator
    if ($py) {
        Write-Host "==> Installing uv with pip into local\.bootstrap"
        & $py.Source -m venv local\.bootstrap
        & "$Root\local\.bootstrap\Scripts\python.exe" -m pip install --quiet uv
        $env:Path = "$Root\local\.bootstrap\Scripts;$env:Path"
    }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required: 'winget install astral-sh.uv' or 'pip install uv' (https://docs.astral.sh/uv/getting-started/installation/), then re-run."
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
