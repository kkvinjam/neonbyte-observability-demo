#!/usr/bin/env bash
# Regenerate the pinned, hash-checked dependency locks for the agent images (linux/arm64, Python 3.13)
# and the cross-platform constraints used for local runs.
#   deploy/scripts/lock-agents.sh                          # resolve as of the date in LOCK_DATE below
#   LOCK_DATE=2026-12-01T00:00:00Z deploy/scripts/lock-agents.sh   # deliberately move forward
# Unpinned rebuilds silently picked up a newer OpenTelemetry/ADOT stack once and the agents stopped
# exporting request spans on AgentCore, so upgrades are explicit: bump LOCK_DATE, redeploy, verify traces.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK_DATE="${LOCK_DATE:-2026-10-30T00:00:00Z}"   # last version set verified end-to-end (GenAI spans in CloudWatch)
cd "$ROOT/agents"
for agent in orchestrator advisor orderdesk support concierge; do
  uv pip compile --quiet --generate-hashes --exclude-newer "$LOCK_DATE" \
    --python-version 3.13 --python-platform aarch64-unknown-linux-gnu \
    "deploy/requirements.$agent.txt" -o "deploy/requirements.$agent.lock"
  echo "  locked $agent ($(grep -c '==' "deploy/requirements.$agent.lock") packages)"
done
uv pip compile --quiet --universal --exclude-newer "$LOCK_DATE" --python-version 3.12 requirements.txt -o constraints.txt
echo "  local constraints: agents/constraints.txt ($(grep -c '==' constraints.txt) packages) — resolved as of $LOCK_DATE"
