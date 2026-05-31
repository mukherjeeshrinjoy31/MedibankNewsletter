#!/bin/bash
set -e

echo "=================================================="
echo "  Create ECS Task Definition for Offer Runner"
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

LAB_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/$LAB_ROLE_NAME"

# Step 1 — Register offer runner task definition
echo ""
echo "[1/2] Registering offer runner task definition..."
aws ecs register-task-definition \
    --family $OFFER_TASK_FAMILY \
    --network-mode awsvpc \
    --requires-compatibilities FARGATE \
    --cpu "2048" \
    --memory "4096" \
    --execution-role-arn $LAB_ROLE_ARN \
    --task-role-arn $LAB_ROLE_ARN \
    --container-definitions "[
        {
            \"name\": \"$CONTAINER_NAME\",
            \"image\": \"$ECR_IMAGE\",
            \"command\": [\"python\", \"-m\", \"src.offer_runner\"],
            \"essential\": true,
            \"logConfiguration\": {
                \"logDriver\": \"awslogs\",
                \"options\": {
                    \"awslogs-group\": \"$LOG_GROUP\",
                    \"awslogs-region\": \"$AWS_REGION\",
                    \"awslogs-stream-prefix\": \"ecs-offer\"
                }
            }
        }
    ]" \
    --query "taskDefinition.taskDefinitionArn" \
    --output text
echo "✓ Offer runner task definition registered: $OFFER_TASK_FAMILY"

# Step 2 — Get default VPC and subnet
echo ""
echo "[2/2] Fetching VPC and subnet info..."
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

echo ""
echo "=================================================="
echo "  Offer Runner ECS Setup Complete!"
echo "=================================================="
echo ""
echo "Task Family:    $OFFER_TASK_FAMILY"
echo "ECR Image:      $ECR_IMAGE"
echo "Command:        python -m src.offer_runner"
echo "VPC ID:         $VPC_ID"
echo "Subnet ID:      $SUBNET_ID"
echo "=================================================="