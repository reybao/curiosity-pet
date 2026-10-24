"""把官方 hexgrad/Kokoro-82M-v1.1-zh 权重转成 mlx-audio 可加载的 safetensors。

官方仓库只有 PyTorch .pth 和 .pt 音色文件。社区 MLX 转换版下载量很少、来源不明,
所以用官方权重本机转换。torch.load 一律 weights_only=True,不执行 pickle 代码。

用法:
    uv run python scripts/convert_kokoro.py            # 输出到 ~/pet-models/kokoro-v1.1-zh
    uv run python scripts/convert_kokoro.py --out DIR
"""

import argparse
import json
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from safetensors.torch import save_file

REPO = "hexgrad/Kokoro-82M-v1.1-zh"
# 只转换实际会用的音色:中文女声、美式英文女声
VOICES = ["zf_001", "zf_002", "zf_003", "af_maple", "af_sol"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "pet-models" / "kokoro-v1.1-zh"))
    args = ap.parse_args()
    out = Path(args.out)
    (out / "voices").mkdir(parents=True, exist_ok=True)

    src = Path(snapshot_download(
        REPO,
        allow_patterns=["config.json", "kokoro-v1_1-zh.pth"] + [f"voices/{v}.pt" for v in VOICES],
    ))

    # .pth 是 {子模块名: state_dict} 的字典,展平成 "子模块.参数名"
    modules = torch.load(src / "kokoro-v1_1-zh.pth", map_location="cpu", weights_only=True)
    flat = {}
    for name, state in modules.items():
        for key, tensor in state.items():
            key = key.removeprefix("module.")
            flat[f"{name}.{key}"] = tensor.contiguous()
    save_file(flat, out / "kokoro-v1_1-zh.safetensors")

    for v in VOICES:
        pack = torch.load(src / "voices" / f"{v}.pt", map_location="cpu", weights_only=True)
        save_file({"voice": pack.contiguous()}, out / "voices" / f"{v}.safetensors")

    # mlx-audio 按 model_type 选择模型类,官方 config 没有这个字段
    config = json.loads((src / "config.json").read_text())
    config["model_type"] = "kokoro"
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
    print(f"已转换 {len(flat)} 个张量、{len(VOICES)} 个音色到 {out}")


if __name__ == "__main__":
    main()
