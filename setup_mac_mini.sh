#!/usr/bin/env bash
# Curiosity Pet: Mac mini (M4, 16GB) 环境安装与基线测试
# 在 pet 账户的终端里运行:  bash setup_mac_mini.sh
# 需要管理员密码的步骤(电源设置)单独列在脚本末尾,用管理员账户执行。
set -euo pipefail

echo "== 0. 硬件检查 =="
sysctl -n machdep.cpu.brand_string
echo "内存: $(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 )) GB"
df -h / | tail -1

echo "== 1. Homebrew =="
if ! command -v brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi
brew update

echo "== 2. 基础工具 =="
brew install ollama uv git node ffmpeg sqlite
# Tailscale 的安装器需要 sudo,非交互运行会失败;失败时在管理员账户手动执行这一行
brew install --cask tailscale || echo "Tailscale 安装需要管理员密码,请手动执行: brew install --cask tailscale"

echo "== 3. 数据目录 =="
mkdir -p ~/pet-data-dev
mkdir -p "$HOME/Library/Application Support/CuriosityPet"
mkdir -p ~/Library/Logs/CuriosityPet
mkdir -p ~/pet-evals/audio ~/pet-evals/questions

echo "== 4. Ollama 常驻服务(自定义 LaunchAgent,带环境变量)=="
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

echo "== 5. 拉取模型 =="
# 用 GGUF q4_K_M 版(llama.cpp 引擎):默认的 qwen3.5:4b 是 nvfp4,走 MLX 引擎,常驻内存随请求持续增长
ollama pull qwen3.5:4b-q4_K_M
ollama pull qwen3-embedding:0.6b
# 对照组,可选: ollama pull gemma4:e4b
# 守卫模型: 若 Ollama 库里没有,后续用 mlx-lm 加载 Qwen/Qwen3Guard-Gen-0.6B
ollama pull qwen3guard:0.6b 2>/dev/null || echo "qwen3guard 不在 Ollama 库中,稍后用 mlx-lm 加载"

echo "== 6. 主模型基线测试(关闭思考,8K 上下文)=="
cat > /tmp/Modelfile.pet <<'EOF'
FROM qwen3.5:4b-q4_K_M
PARAMETER num_ctx 8192
PARAMETER temperature 0.6
EOF
ollama create pet-chat -f /tmp/Modelfile.pet

echo "--- 中文 ---"
time ollama run pet-chat --verbose --think=false \
  "你是一个给7岁孩子讲科学的小伙伴。用两三句话回答:为什么月亮白天也会出现?" 2>&1 | tail -20
echo "--- English ---"
time ollama run pet-chat --verbose --think=false \
  "You explain science to a 7-year-old. In two or three sentences: why is the sky blue?" 2>&1 | tail -20

echo "== 7. 当前引擎与显存 =="
ollama ps

echo "== 8. 语音栈(Python,uv 管理)=="
mkdir -p ~/pet-voice-test && cd ~/pet-voice-test
uv init --no-readme -q --python 3.12 2>/dev/null || true
uv python pin 3.12
uv add mlx-audio mlx-lm silero-vad soundfile numpy fastapi uvicorn sqlite-vec
echo "mlx-audio 已安装。Qwen3-ASR 和 Kokoro 权重在首次调用时自动从 Hugging Face 下载。"

cat <<'EOF'

== 完成。接下来 ==
1. 打开 Tailscale 应用登录(菜单栏)。iPad 也装 Tailscale 登录同一账号。
2. 把上面第 6 步的 tok/s 和首字延迟记下来,这是这台机器的基线。
3. 用管理员账户执行电源设置(见下方)。
4. 在项目目录放入 CLAUDE.md,运行 claude 开始阶段 1。

== 电源设置(管理员账户,需要 sudo)==
sudo pmset -c sleep 0 disksleep 0 displaysleep 10 autorestart 1 womp 1
sudo systemsetup -setrestartfreeze on 2>/dev/null || true
# 系统设置 -> 用户与群组 -> 自动登录: pet(开 FileVault 时重启后需人工输一次密码)
# 系统设置 -> 通用 -> 共享: 打开 远程登录 和 屏幕共享
EOF
