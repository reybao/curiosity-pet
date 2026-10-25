#!/usr/bin/env bash
# Compare engine and KV cache settings for the main model: memory growth (memory_eval) and end-to-end speak latency (latency_eval).
# Each setting runs on a temporary ollama serve (port 11435); the resident LaunchAgent is left untouched.
# Models in the resident service are unloaded first so both do not hold the GPU at once.
#
# Usage: bash evals/engine_matrix.sh [group...]     groups: A B C D, default all
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=11435
URL="http://127.0.0.1:$PORT"
OUT=evals/results/engine-matrix-$(date +%F)
mkdir -p "$OUT"

# group -> "model KV-cache-type" (macOS ships bash 3.2 without associative arrays, so use case)
cfg() {
  case "$1" in
    A) echo "pet-chat-nvfp4 f16" ;;  # MLX, nvfp4(original setup)
    B) echo "pet-chat-nvfp4 q8_0" ;; # MLX, nvfp4
    C) echo "pet-chat-q4km f16" ;;   # llama.cpp, q4_K_M GGUF
    D) echo "pet-chat-q4km q8_0" ;;  # llama.cpp, q4_K_M GGUF
    *) echo "unknown group $1" >&2; exit 1 ;;
  esac
}

ollama create pet-chat-q4km -f evals/modelfiles/pet-chat-q4km.Modelfile >/dev/null
ollama create pet-chat-nvfp4 -f evals/modelfiles/pet-chat-nvfp4.Modelfile >/dev/null

for label in "${@:-A B C D}"; do
  for l in $label; do
    read -r model kv <<<"$(cfg "$l")"
    echo "===== $l: $model, KV $kv"
    for m in $(ollama ps | awk 'NR>1{print $1}'); do ollama stop "$m"; done

    OLLAMA_HOST=127.0.0.1:$PORT OLLAMA_KEEP_ALIVE=-1 OLLAMA_NUM_PARALLEL=1 \
      OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NO_CLOUD=1 OLLAMA_FLASH_ATTENTION=1 \
      OLLAMA_KV_CACHE_TYPE="$kv" ollama serve >"$OUT/serve-$l.log" 2>&1 &
    SERVER=$!
    trap 'kill $SERVER 2>/dev/null || true' EXIT
    until curl -sf "$URL/api/version" >/dev/null; do sleep 0.5; done

    uv run python evals/memory_eval.py --url "$URL" --model "$model" --label "$l" \
      --requests 60 --json "$OUT/memory-$l.json"
    PET_OLLAMA_URL="$URL" PET_CHAT_MODEL="$model" uv run python evals/latency_eval.py \
      --runs 2 --json "$OUT/latency-$l.json" 2>&1 | grep -E "Speak|MLX"
    OLLAMA_HOST=127.0.0.1:$PORT ollama ps | tail -n +2
    grep -iE "kv.?cache|flash|runner|offload" "$OUT/serve-$l.log" | head -5 || true

    kill $SERVER; wait $SERVER 2>/dev/null || true
    trap - EXIT
  done
done
