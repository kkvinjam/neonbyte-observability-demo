#!/usr/bin/env bash
# Run NeonByte on this machine without containers. Everything binds to 127.0.0.1.
#
#   local/run-local.sh            # microservices + storefront + all 5 agents (http transport)
#   local/run-local.sh --no-agents  # microservices + storefront only (no AWS credentials needed)
#   local/run-local.sh --single-agent  # orchestrator calls sub-agents in-process (one agent process)
#
# Agents need AWS credentials with Amazon Bedrock model access (AWS_PROFILE / env vars).
# Stop with Ctrl-C. Logs go to local/logs/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"
LOGS="$ROOT/local/logs"
MODE="${1:-}"
mkdir -p "$LOGS"

if [[ ! -x "$VENV/bin/python" ]]; then
  PY="$(command -v python3.13 || command -v python3.12 || command -v python3)"
  echo "Creating venv at $VENV with $PY"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$ROOT/services/requirements.txt"
  [[ "$MODE" == "--no-agents" ]] || "$VENV/bin/pip" install -q -r "$ROOT/agents/requirements.txt"
fi

export DISABLE_SSM=true AWS_REGION="${AWS_REGION:-us-east-1}"
export CATALOG_URL=http://127.0.0.1:8081 CART_URL=http://127.0.0.1:8082 \
       ORDERS_URL=http://127.0.0.1:8083 PAYMENTS_URL=http://127.0.0.1:8084
PIDS=()
cleanup() { echo; echo "Stopping..."; kill "${PIDS[@]}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

start() {  # name, workdir, command...
  local name="$1" dir="$2"; shift 2
  (cd "$dir" && exec "$@") >"$LOGS/$name.log" 2>&1 &
  PIDS+=($!)
  echo "  started $name (pid $!, log local/logs/$name.log)"
}

echo "Microservices:"
port=8081
for svc in catalog cart orders payments; do
  start "$svc" "$ROOT/services" "$VENV/bin/uvicorn" "$svc.app:app" --host 127.0.0.1 --port "$port"
  port=$((port + 1))
done

if [[ "$MODE" != "--no-agents" ]]; then
  echo "Agents:"
  if [[ "$MODE" == "--single-agent" ]]; then
    AGENT_TRANSPORT=local PORT=8090 start orchestrator "$ROOT/agents" "$VENV/bin/python" -m neonbyte_agents.orchestrator_strands.server
  else
    AGENT_TRANSPORT=http PORT=8090 start orchestrator "$ROOT/agents" "$VENV/bin/python" -m neonbyte_agents.orchestrator_strands.server
    PORT=8091 start advisor "$ROOT/agents" "$VENV/bin/python" -m neonbyte_agents.product_advisor_langgraph.server
    PORT=8092 start orderdesk "$ROOT/agents" "$VENV/bin/python" -m neonbyte_agents.order_desk_crewai.server
    PORT=8093 start support "$ROOT/agents" "$VENV/bin/python" -m neonbyte_agents.support_llamaindex.server
    PORT=8094 start concierge "$ROOT/agents" "$VENV/bin/python" -m neonbyte_agents.concierge_openai.server
  fi
  export ORCHESTRATOR_URL=http://127.0.0.1:8090
fi

echo "Storefront:"
start storefront "$ROOT/services" "$VENV/bin/uvicorn" storefront.app:app --host 127.0.0.1 --port 8080
echo
echo "NeonByte is starting at http://127.0.0.1:8080  (generate traffic: $VENV/bin/python traffic/loadgen.py)"
wait
