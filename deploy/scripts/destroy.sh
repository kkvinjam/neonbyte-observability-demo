#!/usr/bin/env bash
# Delete the NeonByte stack (ECR images, tables and log groups go with it).
#   deploy/scripts/destroy.sh            # delete the stack, keep the artifacts bucket
#   deploy/scripts/destroy.sh --bucket   # ...and empty + delete the artifacts bucket
set -euo pipefail
STACK_NAME="${STACK_NAME:-neonbyte}"
REGION="${AWS_REGION:-$(aws configure get region || true)}"
REGION="${REGION:?set AWS_REGION}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

echo "This permanently deletes stack '$STACK_NAME' in $ACCOUNT/$REGION, including its DynamoDB data and ECR images."
read -r -p "Type the stack name to confirm: " answer
[[ "$answer" == "$STACK_NAME" ]] || { echo "Aborted."; exit 1; }

aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
echo "Waiting for deletion (≈ 10-15 min; CloudFront is the slow part)..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
echo "Stack deleted."

if [[ "${1:-}" == "--bucket" ]]; then
  BUCKET="neonbyte-artifacts-${ACCOUNT}-${REGION}"
  aws s3 rm "s3://$BUCKET" --recursive --only-show-errors && aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION"
  echo "Deleted s3://$BUCKET"
fi
