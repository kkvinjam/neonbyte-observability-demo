#!/usr/bin/env bash
# Deploy (or update) NeonByte into the current AWS account/region with one command.
#
#   deploy/scripts/deploy.sh                       # package this checkout, build images, deploy
#   deploy/scripts/deploy.sh --no-rebuild          # update infra only, keep the current images
#   deploy/scripts/deploy.sh --param LoadGenUsers=10 --param EnableTransactionSearch=false
#
# Env: AWS_REGION / AWS_PROFILE as usual, STACK_NAME (default neonbyte).
# What it does: zips the repo (tracked + untracked, honouring .gitignore), uploads it and the
# template to a private artifacts bucket, then `aws cloudformation deploy`. The stack's
# CodeBuild project builds every image from that zip while the stack waits.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STACK_NAME="${STACK_NAME:-neonbyte}"
REGION="${AWS_REGION:-$(aws configure get region || true)}"
REGION="${REGION:?set AWS_REGION}"
REBUILD=true
PARAMS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-rebuild) REBUILD=false ;;
    --param) PARAMS+=("$2"); shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument $1" >&2; exit 1 ;;
  esac
  shift
done

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="neonbyte-artifacts-${ACCOUNT}-${REGION}"
echo "Account $ACCOUNT · region $REGION · stack $STACK_NAME"

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Creating private artifacts bucket s3://$BUCKET"
  if [[ "$REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
    '{"Rules":[{"ID":"expire-old-sources","Status":"Enabled","Filter":{"Prefix":"source/"},"Expiration":{"Days":30}}]}'
fi

current_tag() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].Parameters[?ParameterKey=='ImageTag'].ParameterValue" --output text 2>/dev/null || true
}
if $REBUILD; then
  TAG="$(date -u +%Y%m%d%H%M%S)-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo local)"
else
  TAG="$(current_tag)"; [[ -n "$TAG" && "$TAG" != "None" ]] || { echo "No existing stack to reuse images from"; exit 1; }
fi

ZIP="$(mktemp -d)/neonbyte-src.zip"
(cd "$ROOT" && { git ls-files --cached --others --exclude-standard 2>/dev/null || find . -type f -not -path './.git/*'; } \
  | grep -v -E '(^|/)(\.venv|node_modules|__pycache__|local/logs)/' | zip -q -@ "$ZIP")
SRC_KEY="source/neonbyte-src-$TAG.zip"
aws s3 cp --only-show-errors "$ZIP" "s3://$BUCKET/$SRC_KEY"
echo "Uploaded source ($TAG) -> s3://$BUCKET/$SRC_KEY"

echo "Deploying stack (first deploy ≈ 25-35 min: image build, AgentCore runtimes, CloudFront)..."
aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --template-file "$ROOT/deploy/cloudformation/neonbyte.yaml" \
  --s3-bucket "$BUCKET" --s3-prefix templates \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --no-fail-on-empty-changeset \
  --parameter-overrides "SourceS3Uri=s3://$BUCKET/$SRC_KEY" "ImageTag=$TAG" ${PARAMS[@]+"${PARAMS[@]}"}

aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
