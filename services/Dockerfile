# One image per microservice, built from this shared context:
#   docker build --build-arg SERVICE=catalog -t neonbyte/catalog services/
FROM public.ecr.aws/docker/library/python:3.13-slim

ARG SERVICE
ENV SERVICE=${SERVICE} PORT=8080 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY ${SERVICE} /app/${SERVICE}

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=3)"]

# 0.0.0.0 inside the container only: on ECS the task ENI sits in a private subnet
# behind security groups; docker compose publishes the storefront to 127.0.0.1 only.
CMD ["sh", "-c", "exec uvicorn ${SERVICE}.app:app --host 0.0.0.0 --port ${PORT}"]
