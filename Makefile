# NeonByte Electronics — common tasks. Run `make help`.
PY ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV ?= .venv

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

venv:  ## create .venv with service + agent + test dependencies
	$(PY) -m venv $(VENV) && $(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r services/requirements.txt -r agents/requirements.txt -r traffic/requirements.txt pytest cfn-lint

test:  ## unit/integration tests (in-memory, no AWS needed)
	$(VENV)/bin/python -m pytest -q tests

lint-cfn:  ## validate the CloudFormation template
	$(VENV)/bin/cfn-lint -r us-east-1 us-west-2 -- deploy/cloudformation/neonbyte.yaml

run-local:  ## run services + agents as local processes (127.0.0.1:8080)
	VENV=$(VENV) local/run-local.sh

run-local-noagents:  ## run services only (no AWS credentials needed)
	VENV=$(VENV) local/run-local.sh --no-agents

compose-up:  ## run everything in containers with Jaeger tracing
	docker compose up --build

load:  ## generate traffic against TARGET (default local storefront)
	$(VENV)/bin/python traffic/loadgen.py --target $${TARGET:-http://127.0.0.1:8080}

lock:  ## re-pin agent image dependencies (LOCK_DATE=... to move forward)
	deploy/scripts/lock-agents.sh

deploy:  ## deploy/update the full stack to AWS (current credentials/region)
	deploy/scripts/deploy.sh

destroy:  ## delete the AWS stack
	deploy/scripts/destroy.sh

.PHONY: help venv test lock lint-cfn run-local run-local-noagents compose-up load deploy destroy
