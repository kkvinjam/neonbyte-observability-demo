# One image per agent — Bedrock AgentCore Runtime requires ARM64.
# Build context is the agents/ directory:
#   docker build --platform linux/arm64 --build-arg AGENT=orchestrator -f deploy/Dockerfile .
# AGENT is one of: orchestrator | advisor | orderdesk | support | concierge
FROM public.ecr.aws/docker/library/python:3.13-slim
ARG AGENT
WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 \
    AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
    AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT=true DOCKER_CONTAINER=1 \
    AGENT=${AGENT}

# Pinned + hash-checked lock (deploy/scripts/lock-agents.sh); never resolve fresh at build time.
COPY deploy/requirements.${AGENT}.lock /tmp/requirements.lock
RUN pip install --no-cache-dir uv && uv pip install --require-hashes --no-deps -r /tmp/requirements.lock

RUN useradd -m -u 1000 bedrock_agentcore
COPY --chown=bedrock_agentcore:bedrock_agentcore neonbyte_agents /app/neonbyte_agents/
COPY --chown=bedrock_agentcore:bedrock_agentcore deploy/entrypoint.sh /app/entrypoint.sh
USER bedrock_agentcore

EXPOSE 8080

# `/ping` is the AgentCore health endpoint; urllib keeps curl out of the slim base image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\", \"8080\")}/ping', timeout=2)"]

CMD ["sh", "/app/entrypoint.sh"]
