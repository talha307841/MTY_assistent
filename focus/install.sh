#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_FOCUS="$HOME/.focus"
CONFIG_PATH="$HOME_FOCUS/config.yaml"
DB_PATH="$HOME_FOCUS/focus.db"
SERVICE_PATH="/etc/systemd/system/focus.service"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

if ! command -v aw-qt >/dev/null 2>&1 && ! command -v aw-server >/dev/null 2>&1; then
  echo "ActivityWatch is not installed. Install it first from https://activitywatch.net"
  exit 1
fi

python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

mkdir -p "$HOME_FOCUS/logs" "$HOME_FOCUS/reports"

if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$PROJECT_DIR/config.yaml" "$CONFIG_PATH"
  echo "Created config at $CONFIG_PATH"
fi

if [[ ! -f "$DB_PATH" ]]; then
  "$PROJECT_DIR/.venv/bin/python" -c "from db.models import init_db; init_db()" 2>/dev/null || true
fi

sudo cp "$PROJECT_DIR/systemd/focus.service" "$SERVICE_PATH"
sudo sed -i "s|%i|$USER|g" "$SERVICE_PATH"
sudo sed -i "s|%h|$HOME|g" "$SERVICE_PATH"
sudo systemctl daemon-reload
sudo systemctl enable focus.service
sudo systemctl restart focus.service

echo "FOCUS installed."
echo "1) Edit $CONFIG_PATH and add nvidia_nim_api_key"
echo "2) Load Chrome extension from: $PROJECT_DIR/chrome-extension"
echo "3) Check service: systemctl status focus.service"
