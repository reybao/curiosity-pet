#!/usr/bin/env bash
# Curiosity Pet: Mac mini (M4, 16GB) environment setup and baseline test
# Run in the pet account's terminal:  bash setup_mac_mini.sh
# Steps that need the admin password (power settings) are listed at the end of the script; run them from the admin account.
set -euo pipefail

echo "== 0. Hardware check =="
sysctl -n machdep.cpu.brand_string
echo "Memory: $(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 )) GB"
df -h / | tail -1

echo "== 1. Homebrew =="
if ! command -v brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
brew update

echo "== 2. Base tools =="
brew install ollama uv git node ffmpeg sqlite
# The Tailscale installer needs sudo and fails when run non-interactively; if it fails, run this line manually from the admin account
brew install --cask tailscale || echo "Tailscale install needs the admin password, please run manually: brew install --cask tailscale"

echo "== 3. Data directories =="
mkdir -p ~/pet-data-dev
mkdir -p "$HOME/Library/Application Support/CuriosityPet"
mkdir -p ~/Library/Logs/CuriosityPet
mkdir -p ~/pet-evals/audio ~/pet-evals/questions

echo "== 4. Ollama resident service (custom LaunchAgent with environment variables)=="
PLIST=~/Library/LaunchAgents/com.curiositypet.ollama.plist
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.curiositypet.ollama</string>
  <key>ProgramArguments</key><array><string>$(brew --prefix)/bin/ollama</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key><dict>
    <key>OLLAMA_HOST</key><string>127.0.0.1:11434</string>
    <key>OLLAMA_KEEP_ALIVE</key><string>-1</string>
    <key>OLLAMA_NUM_PARALLEL</key><string>1</string>
    <key>OLLAMA_MAX_LOADED_MODELS</key><string>3</string>
  </dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/CuriosityPet/ollama.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/CuriosityPet/ollama.err.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 3
ollama --version

echo "== 5. Pull models =="
# Use the GGUF q4_K_M build (llama.cpp engine): the default qwen3.5:4b is nvfp4 and runs on the MLX engine, whose resident memory keeps growing with requests
ollama pull qwen3.5:4b-q4_K_M
ollama pull qwen3-embedding:0.6b
# Control group, optional: ollama pull gemma4:e4b
# Guard model: if it is not in the Ollama library, load Qwen/Qwen3Guard-Gen-0.6B with mlx-lm later
ollama pull qwen3guard:0.6b 2>/dev/null || echo "qwen3guard is not in the Ollama library, load it with mlx-lm later"

echo "== 6. Main model baseline test (thinking off, 8K context)=="
cat > /tmp/Modelfile.pet <<'EOF'
FROM qwen3.5:4b-q4_K_M
PARAMETER num_ctx 8192
PARAMETER temperature 0.6
EOF
ollama create pet-chat -f /tmp/Modelfile.pet

echo "--- Chinese ---"
time ollama run pet-chat --verbose --think=false \
  "你是一个给7岁孩子讲科学的小伙伴。用两三句话回答:为什么月亮白天也会出现?" 2>&1 | tail -20
echo "--- English ---"
time ollama run pet-chat --verbose --think=false \
  "You explain science to a 7-year-old. In two or three sentences: why is the sky blue?" 2>&1 | tail -20

echo "== 7. Current engine and GPU memory =="
ollama ps

echo "== 8. Voice stack (Python, managed by uv)=="
mkdir -p ~/pet-voice-test && cd ~/pet-voice-test
uv init --no-readme -q --python 3.12 2>/dev/null || true
uv python pin 3.12
uv add mlx-audio mlx-lm silero-vad soundfile numpy fastapi uvicorn sqlite-vec
echo "mlx-audio installed. Qwen3-ASR and Kokoro weights are downloaded from Hugging Face automatically on first use."

cat <<'EOF'

== Done. Next steps ==
1. Open the Tailscale app and sign in (menu bar). Install Tailscale on the iPad too and sign in with the same account.
2. Note the tok/s and first-token latency from step 6 above; they are this machine's baseline.
3. Apply the power settings from the admin account (see below).
4. Put CLAUDE.md in the project directory and run claude to start Stage 1.

== Power settings (admin account, needs sudo) ==
sudo pmset -c sleep 0 disksleep 0 displaysleep 10 autorestart 1 womp 1
sudo systemsetup -setrestartfreeze on 2>/dev/null || true
# System Settings -> Users & Groups -> Automatic login: pet (with FileVault on, the password must be typed once by hand after a restart)
# System Settings -> General -> Sharing: turn on Remote Login and Screen Sharing
EOF
