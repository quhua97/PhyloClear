"""Minimal PhyloClear icon (0.01).

The glyph is a three-tip rectangular cladogram drawn on a rounded teal tile:
one short stem on the left, a vertical "comb" and three horizontal branches
ending in dots.  It is intentionally flat and legible down to 16 px.

The same drawing code serves two purposes:

* :func:`app_icon` builds the QIcon used by every window and the About box at
  run time (no resource file to bundle or path to resolve when frozen);
* :func:`write_ico` emits a standard 32-bit BMP-format ``.ico`` for
  ``pyinstaller --icon`` and for Windows Explorer.

Only PySide6 + the standard library are used (no Pillow dependency).
"""

import os
import struct

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QImage, QPainter, QPen, QPixmap,
)

__all__ = ["ICON_SIZES", "render_icon", "app_icon", "write_ico"]

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

_BG = "#11786C"          # calm deep teal
_FG = "#FFFFFF"          # branches and tips
_RADIUS = 56.0           # rounded tile radius at the 256 px reference size


def render_icon(size=256):
    """Return the icon as a transparent, antialiased :class:`QImage`."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size / 256.0

    # Rounded tile.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(_BG)))
    p.drawRoundedRect(QRectF(0, 0, size, size),
                      _RADIUS * s, _RADIUS * s)

    # Cladogram: stem -> vertical comb -> three branches -> tip dots.
    fg = QColor(_FG)
    pen = QPen(fg)
    pen.setWidthF(max(1.15, 13.0 * s))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def pt(x, y):
        return QPointF(x * s, y * s)

    xs, xe, xt = 52.0, 92.0, 181.0
    ys = (56.0, 128.0, 200.0)
    p.drawLine(pt(xs, 128.0), pt(xe, 128.0))
    p.drawLine(pt(xe, ys[0]), pt(xe, ys[2]))
    for y in ys:
        p.drawLine(pt(xe, y), pt(xt, y))

    p.setBrush(QBrush(fg))
    r = 11.0 * s
    for y in ys:
        centre = pt(xt + 11.0, y)
        p.drawEllipse(centre, r, r)
    p.end()
    return image


def app_icon():
    """QIcon with all the usual Windows sizes, for windows and dialogs."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(render_icon(size)))
    return icon


def _dib(image):
    """One 32-bit BGRA DIB (XOR bitmap + all-zero AND mask) for an ICO."""
    size = image.width()
    row_bytes = size * 4
    mask_row = ((size + 31) // 32) * 4
    mask_size = mask_row * size
    header = struct.pack(
        "<IiiHHIIiiII",
        40,                # biSize
        size,              # biWidth
        size * 2,          # biHeight: XOR bitmap followed by AND mask
        1,                 # biPlanes
        32,                # biBitCount
        0,                 # biCompression = BI_RGB
        row_bytes * size + mask_size,
        0, 0, 0, 0,
    )
    pixels = bytearray()
    # BMP rows are stored bottom-up.
    for y in range(size - 1, -1, -1):
        for x in range(size):
            c = image.pixelColor(x, y)
            pixels += bytes((c.blue(), c.green(), c.red(), c.alpha()))
    pixels += bytes(mask_size)   # fully opaque via the alpha channel
    return header + bytes(pixels)


def write_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """Write a standard multi-size ``.ico`` (BMP/DIB entries)."""
    images = [(size, _dib(render_icon(size))) for size in sizes]
    count = len(images)
    offset = 6 + 16 * count
    directory = bytearray()
    for size, dib in images:
        directory += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32, len(dib), offset,
        )
        offset += len(dib)
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, count))
        fh.write(directory)
        for _size, dib in images:
            fh.write(dib)
    return path
