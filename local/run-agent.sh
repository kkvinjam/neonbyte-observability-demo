#!/usr/bin/env sh
# Start ONE NeonByte agent locally (127.0.0.1) — no microservices to start, no AWS stack needed.
#
#   local/run-agent.sh orchestrator            # Strands orchestrator; sub-agents run in-process
#   local/run-agent.sh advisor|orderdesk|support|concierge
#   local/run-agent.sh orchestrator --services # use servers from `local/run-local.sh --no-agents` instead
#
# Defaults (override by exporting before running):
#   NEONBYTE_BACKEND=embedded  catalog/cart/orders/payments run inside the agent process (in-memory data)
#   AGENT_TRANSPORT=local      the orchestrator calls sub-agents in-process
#   DISABLE_SSM=true           ignore any deployed stack's /neonbyte/* parameters in your AWS account
#   PORT                       8090 orchestrator, 8091 advisor, 8092 orderdesk, 8093 support, 8094 concierge
# Needs AWS credentials with Bedrock model access (AWS_PROFILE or access keys) and AWS_REGION.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Run local/setup.sh first." >&2; exit 1; }

case "${1:-}" in
  orchestrator) MODULE=orchestrator_strands;      DEFAULT_PORT=8090 ;;
  advisor)      MODULE=product_advisor_langgraph; DEFAULT_PORT=8091 ;;
  orderdesk)    MODULE=order_desk_crewai;         DEFAULT_PORT=8092 ;;
  support)      MODULE=support_llamaindex;        DEFAULT_PORT=8093 ;;
  concierge)    MODULE=concierge_openai;          DEFAULT_PORT=8094 ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
if [ "${2:-}" = "--services" ]; then NEONBYTE_BACKEND=http; fi

export NEONBYTE_BACKEND="${NEONBYTE_BACKEND:-embedded}"
export AGENT_TRANSPORT="${AGENT_TRANSPORT:-local}"
export DISABLE_SSM="${DISABLE_SSM:-true}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export PORT="${PORT:-$DEFAULT_PORT}"

"$PY" -c "import boto3,sys; sys.exit(0 if boto3.Session().get_credentials() else 1)" 2>/dev/null || {
  echo "No AWS credentials found (AWS_PROFILE / access keys). Agents call Amazon Bedrock and need them." >&2; exit 1; }

echo "Starting $1 on http://127.0.0.1:$PORT  (backend=$NEONBYTE_BACKEND, transport=$AGENT_TRANSPORT, region=$AWS_REGION)"
echo "Try:  $PY local/ask.py --url http://127.0.0.1:$PORT \"Hi Sparky, what do you sell?\""
cd "$ROOT/agents"
exec "$PY" -m "neonbyte_agents.$MODULE.server"
