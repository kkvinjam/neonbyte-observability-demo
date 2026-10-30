# Traffic generator image (runs as the `loadgen` ECS service, or locally via compose --profile load).
FROM public.ecr.aws/docker/library/python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY loadgen.py .
RUN useradd -m -u 1000 loadgen
USER loadgen
ENV PYTHONUNBUFFERED=1
CMD ["python", "loadgen.py"]
