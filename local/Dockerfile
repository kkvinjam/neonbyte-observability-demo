# All-in-one local image: any agent + the embedded microservices, for any machine with
# Docker / Podman / Finch. Multi-arch friendly (builds natively on amd64 and arm64).
#   docker build -f local/Dockerfile -t neonbyte-local .
#   docker run --rm -p 127.0.0.1:8090:8090 --env-file aws.env neonbyte-local            # orchestrator
#   docker run --rm -p 127.0.0.1:8091:8091 --env-file aws.env -e AGENT=advisor neonbyte-local
FROM public.ecr.aws/docker/library/python:3.13-slim
ENV PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1 DOCKER_CONTAINER=1 \
    AGENT=orchestrator NEONBYTE_BACKEND=embedded AGENT_TRANSPORT=local DISABLE_SSM=true \
    AWS_REGION=us-east-1 NEONBYTE_SERVICES_DIR=/app/services
WORKDIR /app
COPY agents/requirements.txt agents/requirements.txt
COPY agents/constraints.txt agents/constraints.txt
COPY local/requirements.txt local/requirements.txt
RUN pip install --no-cache-dir uv && uv pip install --no-cache -r local/requirements.txt
COPY services services
COPY agents/neonbyte_agents agents/neonbyte_agents
COPY local/ask.py local/ask.py
RUN useradd -m -u 1000 neonbyte && chown -R neonbyte /app
USER neonbyte
# The container binds 0.0.0.0 internally; publish it to loopback only (-p 127.0.0.1:...).
CMD ["sh", "-c", "case $AGENT in orchestrator) M=orchestrator_strands; P=8090;; advisor) M=product_advisor_langgraph; P=8091;; orderdesk) M=order_desk_crewai; P=8092;; support) M=support_llamaindex; P=8093;; concierge) M=concierge_openai; P=8094;; *) echo unknown AGENT; exit 1;; esac; export PORT=${PORT:-$P}; cd agents && exec python -m neonbyte_agents.$M.server"]
