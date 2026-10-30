#!/usr/bin/env bash
# Build all NeonByte images for linux/arm64 (Graviton Fargate + AgentCore) and push to ECR.
# Run from the repository root. Used by the stack's CodeBuild project; also works locally
# with Docker/Finch + AWS credentials:
#   deploy/scripts/build-images.sh <account>.dkr.ecr.<region>.amazonaws.com v2
set -euo pipefail
REGISTRY="${1:?usage: build-images.sh <ecr-registry> <image-tag> [repo-prefix]}"
TAG="${2:?image tag required}"
PREFIX="${3:-neonbyte}"
DOCKER="${DOCKER:-docker}"
LOGS="$(mktemp -d)"

aws ecr get-login-password | $DOCKER login --username AWS --password-stdin "$REGISTRY"

build() {  # repo, then docker build args
  local repo="$1"; shift
  local image="$REGISTRY/$PREFIX/$repo"
  if $DOCKER build --platform linux/arm64 -t "$image:$TAG" -t "$image:latest" "$@" >"$LOGS/$repo.log" 2>&1 \
     && $DOCKER push "$image:$TAG" >>"$LOGS/$repo.log" 2>&1 \
     && $DOCKER push "$image:latest" >>"$LOGS/$repo.log" 2>&1; then
    echo "  ✔ $repo"
  else
    echo "  ✘ $repo — build log:"; tail -n 60 "$LOGS/$repo.log"; return 1
  fi
}

echo "Building images ($TAG) into $REGISTRY/$PREFIX/* ..."
pids=()
for svc in storefront catalog cart orders payments; do
  build "$svc" --build-arg SERVICE="$svc" services & pids+=($!)
done
build loadgen traffic & pids+=($!)
for agent in orchestrator advisor orderdesk support concierge; do
  build "agent-$agent" --build-arg AGENT="$agent" -f agents/deploy/Dockerfile agents & pids+=($!)
done

failed=0
for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
[[ $failed -eq 0 ]] && echo "All images pushed." || { echo "Some images failed."; exit 1; }
