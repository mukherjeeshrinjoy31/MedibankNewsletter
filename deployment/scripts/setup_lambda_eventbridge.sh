#!/bin/bash
set -e

echo "=================================================="
echo "  Create EventBridge Schedule for Lambda"
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

ROLE_ARN="arn:aws:iam::$RESEARCH_AWS_ACCOUNT_ID:role/service-role/$ROLE_NAME"
LAMBDA_ARN="arn:aws:lambda:$RESEARCH_AWS_REGION:$RESEARCH_AWS_ACCOUNT_ID:function:$LAMBDA_FUNCTION_NAME"

# Step 1 — Add Lambda permission for EventBridge
echo ""
echo "[1/2] Adding EventBridge permission to Lambda..."
aws lambda add-permission \
    --function-name $LAMBDA_FUNCTION_NAME \
    --statement-id "EventBridgeInvoke" \
    --action "lambda:InvokeFunction" \
    --principal "scheduler.amazonaws.com" \
    --region $RESEARCH_AWS_REGION 2>/dev/null || echo "Permission already exists — skipping."
echo "✓ Permission added"

# Step 2 — Create EventBridge schedule
# Stage 1 runs at cron(0 23 ? * SUN *) = Monday 9am AEST
# Stage 2 runs 1 hour later = cron(0 0 ? * MON *) = Monday 10am AEST
echo ""
echo "[2/2] Creating EventBridge schedule..."
aws scheduler create-schedule \
    --name $BRIEFING_SCHEDULE_NAME \
    --description "Triggers weekly market intelligence briefing for Medibank - P000268DS" \
    --schedule-expression "cron(0 0 ? * MON *)" \
    --schedule-expression-timezone "Australia/Sydney" \
    --flexible-time-window '{"Mode": "OFF"}' \
    --target "{
        \"Arn\": \"$LAMBDA_ARN\",
        \"RoleArn\": \"$ROLE_ARN\"
    }" \
    --region $RESEARCH_AWS_REGION \
    --query "ScheduleArn" \
    --output text
echo "✓ EventBridge schedule created: $BRIEFING_SCHEDULE_NAME"

echo ""
echo "=================================================="
echo "  Lambda EventBridge Setup Complete!"
echo "=================================================="
echo ""
echo "Schedule:    Every Monday 10am AEST (1hr after Stage 1)"
echo "Lambda:      $LAMBDA_FUNCTION_NAME"
echo "Trigger:     $BRIEFING_SCHEDULE_NAME"
echo "Region:      $RESEARCH_AWS_REGION"
echo "=================================================="