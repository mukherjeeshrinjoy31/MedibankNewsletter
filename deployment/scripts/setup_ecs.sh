#!/bin/bash
set -e

echo "=================================================="
echo "  Create ECS Fargate Cluster and Task Definition"
echo "=================================================="

# ---- Config ----
AWS_REGION="us-east-1"
CLUSTER_NAME="medibank-newsletter-cluster"
TASK_FAMILY="medibank-newsletter-task"
CONTAINER_NAME="medibank-newsletter"
ECR_IMAGE="339712734812.dkr.ecr.us-east-1.amazonaws.com/medibank-newsletter:latest"
LOG_GROUP="/ecs/medibank-newsletter"

# ---- Prompt for AWS credentials ----
read -p "Enter AWS Account ID: " AWS_ACCOUNT_ID
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

# Lab role ARN
LAB_ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/LabRole"

# Step 1 — Create CloudWatch log group
echo ""
echo "[1/4] Creating CloudWatch log group..."
aws logs create-log-group \
    --log-group-name $LOG_GROUP \
    --region $AWS_REGION 2>/dev/null || echo "Log group already exists — skipping."
echo "✓ Log group ready: $LOG_GROUP"

# Step 2 — Create ECS cluster
echo ""
echo "[2/4] Creating ECS cluster..."
aws ecs create-cluster \
    --cluster-name $CLUSTER_NAME \
    --capacity-providers FARGATE \
    --region $AWS_REGION 2>/dev/null || echo "Cluster already exists — skipping."
echo "✓ ECS cluster ready: $CLUSTER_NAME"

# Step 3 — Register task definition
echo ""
echo "[3/4] Registering ECS task definition..."
aws ecs register-task-definition \
    --family $TASK_FAMILY \
    --network-mode awsvpc \
    --requires-compatibilities FARGATE \
    --cpu "1024" \
    --memory "2048" \
    --execution-role-arn $LAB_ROLE_ARN \
    --task-role-arn $LAB_ROLE_ARN \
    --container-definitions "[
        {
            \"name\": \"$CONTAINER_NAME\",
            \"image\": \"$ECR_IMAGE\",
            \"essential\": true,
            \"logConfiguration\": {
                \"logDriver\": \"awslogs\",
                \"options\": {
                    \"awslogs-group\": \"$LOG_GROUP\",
                    \"awslogs-region\": \"$AWS_REGION\",
                    \"awslogs-stream-prefix\": \"ecs\"
                }
            }
        }
    ]"
echo "✓ Task definition registered: $TASK_FAMILY"

# Step 4 — Get default VPC and subnet
echo ""
echo "[4/4] Fetching VPC and subnet info..."
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
echo "  ECS Setup Complete!"
echo "=================================================="
echo ""
echo "Cluster:        $CLUSTER_NAME"
echo "Task Family:    $TASK_FAMILY"
echo "ECR Image:      $ECR_IMAGE"
echo "VPC ID:         $VPC_ID"
echo "Subnet ID:      $SUBNET_ID"
echo ""
echo "Save VPC and Subnet IDs — needed for EventBridge."
echo "=================================================="