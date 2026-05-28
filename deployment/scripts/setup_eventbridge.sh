#!/bin/bash
set -e

echo "=================================================="
echo "  Create EventBridge Schedule for ECS Task"
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

# ---- Prompt for AWS credentials ----
read -p "Enter AWS Access Key ID: " AWS_ACCESS_KEY_ID
read -s -p "Enter AWS Secret Access Key: " AWS_SECRET_ACCESS_KEY
echo ""
read -s -p "Enter AWS Session Token: " AWS_SESSION_TOKEN
echo ""

# ---- Set AWS credentials ----
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
export AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN
export AWS_DEFAULT_REGION=$AWS_REGION

# ---- Build ARNs ----
LAB_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/$LAB_ROLE_NAME"
CLUSTER_ARN="arn:aws:ecs:$AWS_REGION:$AWS_ACCOUNT_ID:cluster/$CLUSTER_NAME"

# ---- Get latest task definition ARN ----
echo ""
echo "Fetching latest task definition..."
TASK_DEF_ARN=$(aws ecs describe-task-definition \
    --task-definition $TASK_FAMILY \
    --query "taskDefinition.taskDefinitionArn" \
    --output text)
echo "✓ Task Definition: $TASK_DEF_ARN"

# ---- Get VPC and subnet dynamically ----
echo ""
echo "Fetching VPC and subnet..."
VPC_ID=$(aws ec2 describe-vpcs \
    --filters "Name=isDefault,Values=true" \
    --query "Vpcs[0].VpcId" \
    --output text)

SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query "Subnets[0].SubnetId" \
    --output text)

echo "✓ VPC: $VPC_ID"
echo "✓ Subnet: $SUBNET_ID"

# ---- Create EventBridge schedule ----
echo ""
echo "[1/1] Creating EventBridge schedule..."
aws scheduler create-schedule \
    --name $SCHEDULE_NAME \
    --schedule-expression "cron(0 23 ? * SUN *)" \
    --schedule-expression-timezone "Australia/Melbourne" \
    --flexible-time-window '{"Mode": "OFF"}' \
    --target "{
        \"Arn\": \"$CLUSTER_ARN\",
        \"RoleArn\": \"$LAB_ROLE_ARN\",
        \"EcsParameters\": {
            \"TaskDefinitionArn\": \"$TASK_DEF_ARN\",
            \"TaskCount\": 1,
            \"LaunchType\": \"FARGATE\",
            \"NetworkConfiguration\": {
                \"awsvpcConfiguration\": {
                    \"Subnets\": [\"$SUBNET_ID\"],
                    \"AssignPublicIp\": \"ENABLED\"
                }
            }
        }
    }" \
    --region $AWS_REGION \
    --query "ScheduleArn" \
    --output text
echo "✓ EventBridge schedule created: $SCHEDULE_NAME"

echo ""
echo "=================================================="
echo "  EventBridge Setup Complete!"
echo "=================================================="
echo ""
echo "Schedule:    Every Monday 9am AEST"
echo "Cluster:     $CLUSTER_NAME"
echo "Task:        $TASK_FAMILY"
echo "Subnet:      $SUBNET_ID"
echo ""
echo "To test manually run:"
echo "  bash deployment/scripts/test_run.sh"
echo "=================================================="