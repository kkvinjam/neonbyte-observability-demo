#!/usr/bin/env sh
# One-time setup on macOS, Linux or Windows (WSL / Git Bash): installs everything needed to run the
# NeonByte agents locally. Prerequisites: a POSIX shell and either uv or any Python 3 with pip.
#
#   local/setup.sh
#
# What it does:
#   1. uses uv (https://docs.astral.sh/uv/); if missing, installs it with pip from your package index
#   2. uses uv to download a private Python 3.13 (no system Python needed, nothing global changed)
#   3. creates .venv in the repo and installs local/requirements.txt (agents + embedded services)
#   4. checks for AWS credentials (needed for Amazon Bedrock) and tells you what's missing
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then PATH="$HOME/.local/bin:$PATH"; fi
if ! command -v uv >/dev/null 2>&1; then
  # Installed as a Python package from your configured package index (pip.conf / PIP_INDEX_URL) into a
  # repo-local bootstrap venv — never by piping a remote script into a shell, and nothing global changes.
  PY="$(command -v python3 || command -v python || true)"
  if [ -n "$PY" ]; then
    echo "==> Installing uv with pip into local/.bootstrap"
    "$PY" -m venv local/.bootstrap && local/.bootstrap/bin/python -m pip install --quiet uv
    PATH="$ROOT/local/.bootstrap/bin:$PATH"
  fi
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: install it with 'brew install uv', 'pipx install uv', 'pip install uv' or 'winget install astral-sh.uv'," >&2
  echo "see https://docs.astral.sh/uv/getting-started/installation/ , then re-run local/setup.sh" >&2
  exit 1
fi
echo "==> uv $(uv --version | cut -d' ' -f2)"

echo "==> Python 3.13 + virtualenv (.venv)"
uv python install 3.13 >/dev/null
uv venv --allow-existing --python 3.13 .venv >/dev/null

echo "==> Installing dependencies (first run takes a few minutes)"
VIRTUAL_ENV="$ROOT/.venv" uv pip install --quiet -r local/requirements.txt

echo "==> Checking AWS credentials for Amazon Bedrock"
if .venv/bin/python -c "import boto3,sys; sys.exit(0 if boto3.Session().get_credentials() else 1)" 2>/dev/null; then
  echo "    credentials found (region: ${AWS_REGION:-$(.venv/bin/python -c 'import boto3; print(boto3.Session().region_name or "not set")')})"
else
  echo "    none found. Provide them any standard way before starting an agent, e.g.:"
  echo "      aws sso login --profile <profile> && export AWS_PROFILE=<profile>   (needs AWS CLI v2)"
  echo "      or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN"
fi
cat <<'MSG'

Setup complete. Start an agent (no other servers needed):
  export AWS_REGION=us-east-1            # plus AWS_PROFILE or access keys
  local/run-agent.sh orchestrator        # or: advisor | orderdesk | support | concierge
Then, in another terminal:
  .venv/bin/python local/ask.py "Recommend earbuds under \$300 and add them to my cart"
MSG
