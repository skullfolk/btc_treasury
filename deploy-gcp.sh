#!/usr/bin/env bash
# ============================================================
#  deploy-gcp.sh — One-shot setup script for GCP e2-micro
#  Run this ONCE on the GCP VM after SSH-ing in.
#
#  Usage:
#    chmod +x deploy-gcp.sh
#    ./deploy-gcp.sh
# ============================================================
set -euo pipefail

PROJECT_DIR="$HOME/btc-treasury"
REPO_DIR="$(pwd)"

echo "════════════════════════════════════════════"
echo "  BTC Treasury — GCP e2-micro Setup"
echo "════════════════════════════════════════════"

# ── 1. Install Docker ─────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "▶ Installing Docker…"
  sudo apt-get update -qq
  sudo apt-get install -y -qq ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "✅ Docker installed"
else
  echo "✅ Docker already installed"
fi

# ── 2. Install Docker Compose standalone ─────────────────────────────
if ! command -v docker-compose &>/dev/null; then
  echo "▶ Installing docker-compose…"
  COMPOSE_VERSION="v2.27.0"
  sudo curl -SL \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
  echo "✅ docker-compose installed"
fi

# ── 3. Set up data directory ──────────────────────────────────────────
echo "▶ Creating data directory…"
mkdir -p ./data
echo "✅ ./data ready"

# ── 4. Build & start container ────────────────────────────────────────
echo "▶ Building Docker image (this may take 2–3 minutes)…"
docker-compose build --no-cache

echo "▶ Starting container…"
docker-compose up -d

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ Deployment complete!"
echo ""
echo "  Dashboard: http://$(curl -s ifconfig.me):8000"
echo ""
echo "  Useful commands:"
echo "    docker-compose logs -f          # view logs"
echo "    docker-compose restart          # restart container"
echo "    docker-compose down             # stop container"
echo "════════════════════════════════════════════"
