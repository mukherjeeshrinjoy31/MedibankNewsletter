#!/bin/bash
set -e

echo "=================================================="
echo "  Build Docker Image and Push to ECR"
echo "=================================================="

# ---- Config ----
AWS_REGION="us-east-1"
ECR_REPO_NAME="medibank-newsletter"
PROJECT_DIR="$HOME/MedibankNewsletter"

# ---- Prompt for branch and AWS credentials ----
read -p "Enter branch name (default: main): " BRANCH
BRANCH=${BRANCH:-main}
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

# Step 1 — Pull latest code from GitHub
echo ""
echo "[1/5] Pulling latest code from GitHub..."
cd $PROJECT_DIR
git fetch origin $BRANCH
git reset --hard origin/$BRANCH
echo "✓ Code updated from branch: $BRANCH"

# Step 2 — Create ECR repository
echo ""
echo "[2/5] Creating ECR repository..."
aws ecr create-repository \
    --repository-name $ECR_REPO_NAME \
    --region $AWS_REGION 2>/dev/null || echo "Repository already exists — skipping."
echo "✓ ECR repository ready"

# Step 3 — Authenticate Docker to ECR
echo ""
echo "[3/5] Authenticating Docker to ECR..."
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS \
    --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
echo "✓ Docker authenticated to ECR"

# Step 4 — Build Docker image
echo ""
echo "[4/5] Building Docker image..."
cd $PROJECT_DIR
docker build -t $ECR_REPO_NAME .
echo "✓ Docker image built"

# Step 5 — Tag and push to ECR
echo ""
echo "[5/5] Pushing image to ECR..."
ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME"
docker tag $ECR_REPO_NAME:latest $ECR_URI:latest
docker push $ECR_URI:latest
echo "✓ Image pushed to ECR"

echo ""
echo "=================================================="
echo "  Build and push complete!"
echo "=================================================="
echo ""
echo "ECR Image URI:"
echo "  $ECR_URI:latest"
echo ""
echo "Save this URI — needed for ECS task definition."
echo "=================================================="