#!/bin/bash
set -e

echo "=================================================="
echo "  Create Bedrock Knowledge Base"
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

# Step 1 — Create S3 vector bucket for KB
echo ""
echo "[1/4] Creating S3 vector bucket..."
aws s3api create-bucket \
    --bucket "bedrock-kb-$KB_NAME" \
    --region $RESEARCH_AWS_REGION 2>/dev/null || echo "Vector bucket already exists — skipping."
echo "✓ S3 vector bucket ready"

# Step 2 — Create Knowledge Base
echo ""
echo "[2/4] Creating Bedrock Knowledge Base..."
KB_RESPONSE=$(aws bedrock-agent create-knowledge-base \
    --name $KB_NAME \
    --role-arn $ROLE_ARN \
    --knowledge-base-configuration '{
        "type": "VECTOR",
        "vectorKnowledgeBaseConfiguration": {
            "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
            "embeddingModelConfiguration": {
                "bedrockEmbeddingModelConfiguration": {
                    "dimensions": 1024
                }
            }
        }
    }' \
    --storage-configuration "{
        \"type\": \"S3_VECTORS\",
        \"s3VectorsConfiguration\": {
            \"bucketArn\": \"arn:aws:s3:::bedrock-kb-$KB_NAME\",
            \"vectorIndexName\": \"$KB_NAME-index\"
        }
    }" \
    --region $RESEARCH_AWS_REGION)

KB_ID=$(echo $KB_RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['knowledgeBase']['knowledgeBaseId'])")
echo "✓ Knowledge Base created: $KB_ID"

# Step 3 — Add S3 data source
echo ""
echo "[3/4] Adding S3 data source..."
DS_ID=$(aws bedrock-agent create-data-source \
    --knowledge-base-id $KB_ID \
    --name "$KB_NAME-ds" \
    --data-source-configuration "{
        \"type\": \"S3\",
        \"s3Configuration\": {
            \"bucketArn\": \"arn:aws:s3:::$S3_KB_BUCKET\",
            \"inclusionPrefixes\": [\"raw/newsletter/json/\"]
        }
    }" \
    --region $RESEARCH_AWS_REGION \
    --query "dataSource.dataSourceId" \
    --output text)
echo "✓ Data source added: s3://$S3_KB_BUCKET/raw/newsletter/json/"

# Step 4 — Start initial sync
echo ""
echo "[4/4] Starting initial sync..."
aws bedrock-agent start-ingestion-job \
    --knowledge-base-id $KB_ID \
    --data-source-id $DS_ID \
    --region $RESEARCH_AWS_REGION \
    --query "ingestionJob.ingestionJobId" \
    --output text
echo "✓ Initial sync started"

echo ""
echo "=================================================="
echo "  Knowledge Base Setup Complete!"
echo "=================================================="
echo ""
echo "KB Name:     $KB_NAME"
echo "KB ID:       $KB_ID"
echo "Data Source: s3://$S3_KB_BUCKET/raw/newsletter/json/"
echo "Region:      $RESEARCH_AWS_REGION"
echo ""
echo "IMPORTANT: Save KB ID — needed for setup_lambda.sh"
echo "KB_ID=$KB_ID"
echo "=================================================="