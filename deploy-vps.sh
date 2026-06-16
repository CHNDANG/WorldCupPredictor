#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/worldcup-predictor}"
REPO_URL="${REPO_URL:-https://github.com/CHNDANG/WorldCupPredictor.git}"
BRANCH="${BRANCH:-main}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root, for example: sudo bash deploy-vps.sh"
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl git

if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cat >/etc/systemd/system/worldcup-predictor.service <<SERVICE
[Unit]
Description=WorldCupPredictor 15-second live updater
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose up -d --build
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable worldcup-predictor
systemctl restart worldcup-predictor

echo "WorldCupPredictor is starting."
echo "Open: http://$(curl -fsS ifconfig.me || hostname -I | awk '{print $1}'):4173/worldcup-predictions.html"
echo "Health: curl http://127.0.0.1:4173/healthz"
echo "Status: curl http://127.0.0.1:4173/api/status.json"
