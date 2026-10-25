"""Convert the official Qwen/Qwen3Guard-Gen-0.6B weights to a 4-bit MLX model on this machine.

Only official weights are used (community uploads on Ollama have unclear provenance), the same rule as for Kokoro.
Usage: uv run --group guard python scripts/convert_guard.py   # writes ~/pet-models/qwen3guard-gen-0.6b-4bit
"""

import argparse
from pathlib import Path

REPO = "Qwen/Qwen3Guard-Gen-0.6B"


def main():
    from mlx_lm import convert

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "pet-models" / "qwen3guard-gen-0.6b-4bit"))
    args = ap.parse_args()
    convert(REPO, mlx_path=args.out, quantize=True, q_bits=4, q_group_size=64)
    print(f"Converted {REPO} to {args.out}")


if __name__ == "__main__":
    main()
