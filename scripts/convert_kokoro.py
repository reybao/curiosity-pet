"""Convert the official hexgrad/Kokoro-82M-v1.1-zh weights into safetensors loadable by mlx-audio.

The official repo ships only PyTorch .pth and .pt voice files. Community MLX conversions have few downloads and unclear provenance,
so convert the official weights locally. torch.load always uses weights_only=True, so no pickle code is executed.

Usage:
    uv run python scripts/convert_kokoro.py            # writes to ~/pet-models/kokoro-v1.1-zh
    uv run python scripts/convert_kokoro.py --out DIR
    uv run python scripts/convert_kokoro.py --voices all --voices-only   # every official voice, for skins to choose from
"""

import argparse
import json
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from safetensors.torch import save_file

REPO = "hexgrad/Kokoro-82M-v1.1-zh"
# Default voices: Chinese female, American English female. Skins may pick others (skin.json "voice"); convert them with --voices.
VOICES = ["zf_001", "zf_002", "zf_003", "af_maple", "af_sol"]


def official_voices() -> list[str]:
    from huggingface_hub import list_repo_files

    return sorted(f[len("voices/"):-len(".pt")] for f in list_repo_files(REPO) if f.startswith("voices/") and f.endswith(".pt"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "pet-models" / "kokoro-v1.1-zh"))
    ap.add_argument("--voices", default=",".join(VOICES), help='comma-separated voice names, or "all"')
    ap.add_argument("--voices-only", action="store_true", help="convert voices only, keep the existing model weights")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "voices").mkdir(parents=True, exist_ok=True)
    voices = official_voices() if args.voices == "all" else [v.strip() for v in args.voices.split(",") if v.strip()]
    model_files = [] if args.voices_only else ["config.json", "kokoro-v1_1-zh.pth"]

    src = Path(snapshot_download(REPO, allow_patterns=model_files + [f"voices/{v}.pt" for v in voices]))
    if args.voices_only:
        for v in voices:
            pack = torch.load(src / "voices" / f"{v}.pt", map_location="cpu", weights_only=True)
            save_file({"voice": pack.contiguous()}, out / "voices" / f"{v}.safetensors")
        print(f"Converted {len(voices)} voices to {out / 'voices'}")
        return

    # .pth is a dict of {submodule name: state_dict}; flatten to "submodule.param name"
    modules = torch.load(src / "kokoro-v1_1-zh.pth", map_location="cpu", weights_only=True)
    flat = {}
    for name, state in modules.items():
        for key, tensor in state.items():
            key = key.removeprefix("module.")
            flat[f"{name}.{key}"] = tensor.contiguous()
    save_file(flat, out / "kokoro-v1_1-zh.safetensors")

    for v in voices:
        pack = torch.load(src / "voices" / f"{v}.pt", map_location="cpu", weights_only=True)
        save_file({"voice": pack.contiguous()}, out / "voices" / f"{v}.safetensors")

    # mlx-audio picks the model class by model_type, which the official config lacks
    config = json.loads((src / "config.json").read_text())
    config["model_type"] = "kokoro"
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"Converted {len(flat)} tensors and {len(voices)} voices to {out}")


if __name__ == "__main__":
    main()
