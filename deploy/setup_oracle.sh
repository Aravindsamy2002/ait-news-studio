#!/usr/bin/env bash
# One-time setup for AIT News 24/7 on an Oracle Cloud Always Free Ampere A1 VM
# (Ubuntu 22.04 / 24.04, ARM64, 4 OCPU / 24 GB). Run from the project folder:
#     bash deploy/setup_oracle.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${SUDO_USER:-$USER}"
MODEL="${ANALYSIS_MODEL:-qwen2.5:3b}"

echo "==> System packages"
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip ffmpeg espeak-ng curl

echo "==> Python environment"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ "${ANALYSIS_ENABLED:-0}" = "1" ]; then
  echo "==> Ollama (local LLM for the optional 'what it means' explainer)"
  if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  sudo systemctl enable --now ollama
  ollama pull "$MODEL"
else
  echo "==> Skipping Ollama (analysis is off; rerun with ANALYSIS_ENABLED=1 to add it)"
fi

echo "==> Kokoro voice model"
cd "$APP_DIR"
"$APP_DIR/.venv/bin/python" -c "from voice_engine import get_kokoro; get_kokoro(); print('Kokoro ready')"

echo "==> Secrets file (/etc/ait-news/env)"
sudo mkdir -p /etc/ait-news
if [ ! -f /etc/ait-news/env ]; then
  sudo tee /etc/ait-news/env >/dev/null <<EOF
# Paste your YouTube Live stream key after the = sign
YOUTUBE_STREAM_KEY=
IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg
RENDER_WORKERS=1
ANALYSIS_ENABLED=${ANALYSIS_ENABLED:-0}
ANALYSIS_MODEL=$MODEL
EOF
fi
sudo chown root:"$APP_USER" /etc/ait-news/env
sudo chmod 640 /etc/ait-news/env

echo "==> systemd service"
sudo tee /etc/systemd/system/ait-news.service >/dev/null <<EOF
[Unit]
Description=AIT News 24/7 autopilot (feeds -> render queue -> YouTube Live)
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/ait-news/env
ExecStart=$APP_DIR/.venv/bin/python autopilot.py
Restart=always
RestartSec=15
Nice=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable ait-news

cat <<'EOF'

Setup complete. Next steps:
  1. sudo nano /etc/ait-news/env        # paste YOUTUBE_STREAM_KEY=...
  2. sudo systemctl start ait-news
  3. journalctl -u ait-news -f          # watch the live log

Dry run without YouTube (writes a local file for 5 minutes):
  .venv/bin/python autopilot.py --output /tmp/test.flv --minutes 5
EOF
