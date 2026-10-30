#!/usr/bin/env bash
# Apply the NeonByte manifests to the EKS cluster and report the ALB endpoints.
# Run by the stack's CodeBuild project (repo root as cwd); writes /tmp/cfn-data.json, which the
# buildspec returns to CloudFormation as the K8sApp custom resource's attributes.
# Needs: CLUSTER_NAME REGISTRY IMAGE_TAG AWS_REGION PRODUCTS_TABLE CARTS_TABLE ORDERS_TABLE
#        PUBLIC_ALB_SG INTERNAL_ALB_SG [REPLICAS LOADGEN_REPLICAS LOADGEN_USERS LOADGEN_CHAT_PROBABILITY]
set -euo pipefail
: "${CLUSTER_NAME:?}" "${AWS_REGION:?}"

if ! command -v kubectl >/dev/null; then
  minor="$(aws eks describe-cluster --name "$CLUSTER_NAME" --query cluster.version --output text)"
  ver="$(curl -fsSL "https://dl.k8s.io/release/stable-${minor}.txt")"
  curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${ver}/bin/linux/$(uname -m | sed 's/aarch64/arm64/;s/x86_64/amd64/')/kubectl"
  chmod +x /usr/local/bin/kubectl
fi
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" >/dev/null

diagnose() (  # runs on any failure so the CodeBuild log says *why*; subshell so `set +e` can't leak
  set +e
  echo "================ DIAGNOSTICS (failed at line $1) ================"
  kubectl get nodes -o wide; kubectl get nodeclaims,nodepools 2>/dev/null
  kubectl get pods -A -o wide
  kubectl -n neonbyte get deploy,rs,ingress,svc
  kubectl get events -A --sort-by=.lastTimestamp | tail -60
  for ing in storefront backends; do kubectl -n neonbyte describe ingress "$ing" | tail -25; done
  for pod in $(kubectl -n neonbyte get pods --no-headers | awk '$3!="Running" || $2 !~ /^([0-9]+)\/\1$/ {print $1}' | head -6); do
    echo "---- pod $pod"; kubectl -n neonbyte describe pod "$pod" | tail -40
    kubectl -n neonbyte logs "$pod" --all-containers --tail=60 2>&1 | tail -60
    kubectl -n neonbyte logs "$pod" --all-containers --previous --tail=40 2>/dev/null | tail -40
  done
  kubectl -n amazon-cloudwatch get pods -o wide; kubectl -n amazon-cloudwatch get deploy
  echo "================================================================="
)
trap 'diagnose $LINENO; exit 1' ERR

# The CloudWatch operator only instruments pods created after its webhook is up.
kubectl -n amazon-cloudwatch wait --for=condition=Available deployment --all --timeout=15m

python3 deploy/k8s/render.py > /tmp/neonbyte-k8s.yaml
# CRDs for Auto Mode (NodePool, IngressClassParams) are present from cluster creation.
kubectl apply -f /tmp/neonbyte-k8s.yaml

for d in storefront catalog cart orders payments loadgen; do
  kubectl -n neonbyte rollout status "deploy/$d" --timeout=15m
done

# Verify Application Signals injection (init container added by the operator); retry once if missing.
init="$(kubectl -n neonbyte get pod -l app=storefront -o jsonpath='{.items[0].spec.initContainers[*].name}')"
if [[ "$init" != *opentelemetry-auto-instrumentation-python* ]]; then
  echo "instrumentation not injected yet (init: '${init}'); restarting deployments"
  kubectl -n neonbyte rollout restart deploy storefront catalog cart orders payments
  for d in storefront catalog cart orders payments; do kubectl -n neonbyte rollout status "deploy/$d" --timeout=10m; done
fi

hostname_of() {  # wait for the controller to provision an ALB for ingress $1
  local h=""
  for _ in $(seq 1 90); do
    h="$(kubectl -n neonbyte get ingress "$1" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
    [[ -n "$h" ]] && { echo "$h"; return 0; }
    sleep 10
  done
  echo "ingress $1 got no load balancer; events:" >&2
  kubectl -n neonbyte describe ingress "$1" >&2 || true
  return 1
}
PUBLIC_DNS="$(hostname_of storefront)"
INTERNAL_DNS="$(hostname_of backends)"
PUBLIC_ARN="$(aws elbv2 describe-load-balancers --query "LoadBalancers[?DNSName=='${PUBLIC_DNS}'].LoadBalancerArn" --output text)"

[[ -n "$PUBLIC_DNS" && -n "$INTERNAL_DNS" && "$PUBLIC_ARN" == arn:* ]] || { echo "missing ALB data" >&2; exit 1; }
python3 - "$PUBLIC_DNS" "$INTERNAL_DNS" "$PUBLIC_ARN" > /tmp/cfn-data.tmp <<'PY'
import json, sys
public_dns, internal_dns, public_arn = sys.argv[1:4]
print(json.dumps({
    "StorefrontAlbDns": public_dns,
    "StorefrontAlbFullName": public_arn.split(":loadbalancer/", 1)[1],
    "InternalAlbDns": internal_dns,
}))
PY
mv /tmp/cfn-data.tmp /tmp/cfn-data.json
echo "Applied. storefront ALB: $PUBLIC_DNS · internal ALB: $INTERNAL_DNS"
