#!/bin/bash
set -e

echo "=================================================="
echo "  Trigger Lambda Function Manually"
echo "=================================================="

# ---- Load config ----
PROJECT_DIR="$HOME/MedibankNewsletter"
CONFIG_FILE="$PROJECT_DIR/deployment/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: config.env not found at $CONFIG_FILE"
    exit 1
fi
source $CONFIG_FILE
echo "✓ Config loaded"

export AWS_DEFAULT_REGION=$RESEARCH_AWS_REGION

# ---- Invoke Lambda ----
echo ""
echo "Triggering Lambda function: $LAMBDA_FUNCTION_NAME..."
aws lambda invoke \
    --function-name $LAMBDA_FUNCTION_NAME \
    --region $RESEARCH_AWS_REGION \
    --log-type Tail \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    response.json

echo "✓ Lambda triggered"
echo ""
echo "Response:"
cat response.json
rm -f response.json

echo ""
echo "Monitor logs at:"
echo "  CloudWatch → Log Groups → /aws/lambda/$LAMBDA_FUNCTION_NAME"
echo ""
echo "Check status:"
echo "  aws lambda get-function --function-name $LAMBDA_FUNCTION_NAME --region $RESEARCH_AWS_REGION"
echo "=================================================="