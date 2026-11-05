"""把用户提供的原始 PNG 图标放大并转换成多尺寸 .ico + 256px png。

源图: 深色圆角底 + 白色空心方框，尺寸很小，因此用 LANCZOS 放大到 256×256。
用法: python build/make_icon.py <源 png> <输出目录>
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def build(src: Path, out_dir: Path) -> tuple[Path, Path]:
    img = Image.open(src).convert("RGBA")
    canvas = img.resize((256, 256), Image.LANCZOS)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "icon.png"
    canvas.save(png, format="PNG")
    ico = out_dir / "icon.ico"
    canvas.save(ico, format="ICO", sizes=ICO_SIZES)
    return ico, png


if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("assets")
    print(*build(src, out), sep="\n")
