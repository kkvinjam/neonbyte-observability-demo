# Start ONE NeonByte agent locally on Windows (127.0.0.1) — no microservices or AWS stack needed.
#   powershell -File local\run-agent.ps1 orchestrator    # or advisor | orderdesk | support | concierge
# Same defaults as local/run-agent.sh: embedded backend, in-process sub-agents, SSM disabled.
param([Parameter(Mandatory = $true)][ValidateSet("orchestrator", "advisor", "orderdesk", "support", "concierge")][string]$Agent,
      [switch]$Services)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$py = "$Root\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run local\setup.ps1 first." }
$map = @{ orchestrator = @("orchestrator_strands", 8090); advisor = @("product_advisor_langgraph", 8091);
          orderdesk = @("order_desk_crewai", 8092); support = @("support_llamaindex", 8093); concierge = @("concierge_openai", 8094) }
$module, $port = $map[$Agent]
if (-not $env:NEONBYTE_BACKEND) { $env:NEONBYTE_BACKEND = $(if ($Services) { "http" } else { "embedded" }) }
if (-not $env:AGENT_TRANSPORT) { $env:AGENT_TRANSPORT = "local" }
if (-not $env:DISABLE_SSM) { $env:DISABLE_SSM = "true" }
if (-not $env:AWS_REGION) { $env:AWS_REGION = "us-east-1" }
if (-not $env:PORT) { $env:PORT = "$port" }
Write-Host "Starting $Agent on http://127.0.0.1:$($env:PORT) (backend=$($env:NEONBYTE_BACKEND), region=$($env:AWS_REGION))"
Set-Location "$Root\agents"
& $py -m "neonbyte_agents.$module.server"
