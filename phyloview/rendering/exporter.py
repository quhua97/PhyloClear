"""Export the tree visualization to raster (PNG/JPEG) or vector (SVG/PDF)."""

from PySide6.QtCore import QRectF, QMarginsF, QFileInfo
from PySide6.QtGui import (
    QImage,
    QPainter,
    QPageLayout,
    QPageSize,
    QPdfWriter,
)
from PySide6.QtSvg import QSvgGenerator

# Exported raster images use 300 dpi on BOTH axes by default: the width and the
# height are scaled from the same factor, so the drawing is never stretched.
#
# The scene is laid out in "screen pixels", where one pixel is 1/96 inch at the
# standard logical resolution, so printing at 300 dpi means scaling the drawing
# by 300/96 (~3.1x) and stamping the same resolution into the file metadata.
EXPORT_DPI = 300
LOGICAL_DPI = 96.0


def _raster_size(rect, dpi=EXPORT_DPI, width=None):
    """Pixel size of ``rect`` when rendered at ``dpi`` (both axes identical)."""
    if dpi <= 0:
        dpi = EXPORT_DPI
    if width is not None:
        # Caller asked for an explicit pixel width: keep the aspect ratio and
        # report the resolution that width implies for both axes.
        width = int(width)
        if rect.width() > 0:
            height = int(round(rect.height() * (width / rect.width())))
        else:
            height = width
        return max(1, width), max(1, height)
    scale = dpi / LOGICAL_DPI
    return (max(1, int(round(rect.width() * scale))),
            max(1, int(round(rect.height() * scale))))


def _stamp_dpi(image, rect, pixel_width, dpi=EXPORT_DPI):
    """Write the DPI metadata into the image (width and height identical)."""
    if dpi <= 0:
        dpi = EXPORT_DPI
    if rect.width() > 0 and pixel_width > 0:
        # Resolution really obtained, so that a caller-specified pixel width
        # still reports the correct value instead of a wrong fixed number.
        dpi = pixel_width / (rect.width() / LOGICAL_DPI)
    dots_per_metre = int(round(dpi / 0.0254))
    image.setDotsPerMeterX(dots_per_metre)
    image.setDotsPerMeterY(dots_per_metre)


def _target_rect(scene):
    # Use the *items* bounding box, not sceneRect(): since 1.3 the canvas
    # keeps the scene rect larger than the tree (free panning room), and that
    # empty margin must not end up in the exported image.
    rect = scene.itemsBoundingRect()
    # fallback to scene rect if the items rect is degenerate
    if rect.isNull() or rect.width() <= 1 or rect.height() <= 1:
        rect = scene.sceneRect()
    return rect.adjusted(-20, -20, 20, 20)


def export_png(scene, path, width=None, dpi=EXPORT_DPI):
    """Render the scene to a PNG at ``dpi`` dots per inch (300 by default)."""
    rect = _target_rect(scene)
    width, height = _raster_size(rect, dpi=dpi, width=width)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    _stamp_dpi(image, rect, width, dpi)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene.render(painter, QRectF(0, 0, width, height), rect)
    painter.end()
    return image.save(path)


def export_jpeg(scene, path, width=None, quality=95, dpi=EXPORT_DPI):
    """Render the scene to a JPEG at ``dpi`` dots per inch (300 by default)."""
    rect = _target_rect(scene)
    width, height = _raster_size(rect, dpi=dpi, width=width)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    _stamp_dpi(image, rect, width, dpi)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene.render(painter, QRectF(0, 0, width, height), rect)
    painter.end()
    return image.save(path, "JPEG", quality)


def export_svg(scene, path):
    rect = _target_rect(scene)
    generator = QSvgGenerator()
    generator.setFileName(path)
    generator.setSize(rect.size().toSize())
    generator.setViewBox(rect)
    generator.setTitle("PhyloClear tree")
    generator.setDescription("Exported from PhyloClear")
    painter = QPainter(generator)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene.render(painter, rect, rect)
    painter.end()
    return True


def export_pdf(scene, path):
    rect = _target_rect(scene)
    writer = QPdfWriter(path)
    page = QPageSize(QPageSize.PageSizeId.A4)
    writer.setPageSize(page)
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setResolution(EXPORT_DPI)
    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # fit scene rect into the page's paint area
    target = writer.pageLayout().paintRectPixels(writer.resolution())
    target = QRectF(target)
    scene.render(painter, target, rect)
    painter.end()
    return True


EXPORTERS = {
    "png": export_png,
    "jpg": export_jpeg,
    "jpeg": export_jpeg,
    "svg": export_svg,
    "pdf": export_pdf,
}


def export_scene(scene, path):
    """Export based on file extension. Returns True on success."""
    import os

    ext = os.path.splitext(path)[1].lstrip(".").lower()
    fn = EXPORTERS.get(ext)
    if fn is None:
        raise ValueError("Unsupported export format: %s" % ext)
    return fn(scene, path)
