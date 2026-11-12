#!/usr/bin/env python3
"""Render assets/stella.svg to PNG sizes with QtSvg (build-time only)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

try:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage, QPainter
except ImportError:
    print("QtSvg not available; cannot render PNGs", file=sys.stderr)
    raise SystemExit(1)

app = QGuiApplication([])
renderer = QSvgRenderer(str(ASSETS / "stella.svg"))
for size in (512, 256, 128, 64):
    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    out = ASSETS / f"stella-{size}.png"
    image.save(str(out))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
# Default icon name used by the .desktop file.
src = ASSETS / "stella-256.png"
dst = ASSETS / "stella.png"
dst.write_bytes(src.read_bytes())
print(f"wrote {dst}")
