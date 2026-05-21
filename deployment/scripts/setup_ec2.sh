#!/bin/bash
set -e

echo "=================================================="
echo "  Medibank Newsletter — EC2 Setup"
echo "=================================================="

# ---- Config ----
GITHUB_REPO="https://github.com/mukherjeeshrinjoy31/MedibankNewsletter.git"
PROJECT_DIR="$HOME/MedibankNewsletter"

# ---- Prompt for branch ----
read -p "Enter branch name (default: main): " BRANCH
BRANCH=${BRANCH:-main}

# Step 1 — Update system
echo ""
echo "[1/5] Updating system..."
sudo apt update && sudo apt upgrade -y

# Step 2 — Install dependencies
echo ""
echo "[2/5] Installing Git, Docker, AWS CLI..."
sudo apt install -y git docker.io awscli

sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ubuntu
echo "✓ Docker installed"
echo "✓ AWS CLI installed"
echo "✓ Git installed"

# Step 3 — Clone repo
echo ""
echo "[3/5] Cloning repository..."
if [ -d "$PROJECT_DIR" ]; then
    echo "Directory exists — pulling latest..."
    cd "$PROJECT_DIR"
    git pull origin "$BRANCH"
else
    git clone -b "$BRANCH" "$GITHUB_REPO" "$PROJECT_DIR"
fi
echo "✓ Code cloned from GitHub"

# Step 4 — Create logs directory
echo ""
echo "[4/5] Creating logs directory..."
mkdir -p "$PROJECT_DIR/logs"
echo "✓ Logs directory created"

# Step 5 — Verify
echo ""
echo "[5/5] Verifying installations..."
docker --version
aws --version
git --version

echo ""
echo "=================================================="
echo "  Setup complete!"
echo "=================================================="
echo ""
echo "IMPORTANT: Log out and log back in via Putty"
echo "for Docker group changes to take effect."
echo "=================================================="