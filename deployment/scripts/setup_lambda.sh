#!/bin/bash
set -e

echo "=================================================="
echo "  Create Lambda Function for Newsletter Briefing"
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

# ---- Prompt for KB ID ----
read -p "Enter Knowledge Base ID: " KB_ID

export AWS_DEFAULT_REGION=$RESEARCH_AWS_REGION

ROLE_ARN="arn:aws:iam::$RESEARCH_AWS_ACCOUNT_ID:role/service-role/$ROLE_NAME"
LAMBDA_DIR="$PROJECT_DIR/deployment/lambda"
LAMBDA_ZIP="$LAMBDA_DIR/lambda_function.zip"

# Step 1 — Package Lambda function
echo ""
echo "[1/4] Packaging Lambda function..."
mkdir -p "$LAMBDA_DIR"
cp "$PROJECT_DIR/src/lambda_handler.py" "$LAMBDA_DIR/lambda_function.py"
cd "$LAMBDA_DIR"
zip -r lambda_function.zip lambda_function.py
echo "✓ Lambda function packaged"

# Step 2 — Create Lambda function
echo ""
echo "[2/4] Creating Lambda function..."
LAMBDA_ARN=$(aws lambda create-function \
    --function-name $LAMBDA_FUNCTION_NAME \
    --description "AI-driven weekly market intelligence briefing for Medibank - P000268DS, RMIT University" \
    --runtime python3.12 \
    --role $ROLE_ARN \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://$LAMBDA_ZIP \
    --timeout 300 \
    --memory-size 128 \
    --ephemeral-storage '{"Size": 512}' \
    --region $RESEARCH_AWS_REGION \
    --query "FunctionArn" \
    --output text 2>/dev/null || \
aws lambda update-function-code \
    --function-name $LAMBDA_FUNCTION_NAME \
    --zip-file fileb://$LAMBDA_ZIP \
    --region $RESEARCH_AWS_REGION \
    --query "FunctionArn" \
    --output text)
echo "✓ Lambda function created: $LAMBDA_FUNCTION_NAME"

# Step 3 — Set environment variables
echo ""
echo "[3/4] Setting environment variables..."
aws lambda update-function-configuration \
    --function-name $LAMBDA_FUNCTION_NAME \
    --environment "Variables={
        KNOWLEDGE_BASE_ID=$KB_ID,
        EMAIL_SENDER=$EMAIL_SENDER,
        EMAIL_RECIPIENTS=$EMAIL_RECIPIENTS,
        REGION=$RESEARCH_AWS_REGION
    }" \
    --region $RESEARCH_AWS_REGION
echo "✓ Environment variables set"

# Step 4 — Verify
echo ""
echo "[4/4] Verifying Lambda function..."
aws lambda get-function \
    --function-name $LAMBDA_FUNCTION_NAME \
    --region $RESEARCH_AWS_REGION \
    --query "Configuration.{State:State,Runtime:Runtime,Timeout:Timeout,MemorySize:MemorySize}" \
    --output table
echo "✓ Lambda function verified"

echo ""
echo "=================================================="
echo "  Lambda Setup Complete!"
echo "=================================================="
echo ""
echo "Function:    $LAMBDA_FUNCTION_NAME"
echo "Runtime:     python3.12"
echo "Timeout:     300s (5 min)"
echo "Memory:      128MB"
echo "Storage:     512MB"
echo "KB ID:       $KB_ID"
echo "Region:      $RESEARCH_AWS_REGION"
echo ""
echo "IMPORTANT: Save Lambda ARN — needed for setup_lambda_eventbridge.sh"
echo "Lambda ARN:  $LAMBDA_ARN"
echo "=================================================="