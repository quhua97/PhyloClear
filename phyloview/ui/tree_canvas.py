"""Interactive tree canvas: a QGraphicsView with pan, zoom and drag-drop."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QBrush
from PySide6.QtWidgets import (
    QGraphicsView, QApplication, QGraphicsItem,
)

from ..rendering.items import BranchItem, NodeMarkerItem, AnnotationTextItem


class TreeCanvas(QGraphicsView):
    """Displays the tree scene with mouse pan, wheel zoom and file drag-drop."""

    nodeSelected = Signal(object)          # Node or None
    fileDropped = Signal(str)              # absolute path

    # Zoom limits prevent extreme transforms that freeze or crash the view.
    MIN_ZOOM = 0.05
    MAX_ZOOM = 60.0
    WHEEL_STEP = 1.15

    def __init__(self, renderer, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self.setScene(renderer.scene)
        # NOTE: avoid SmoothPixmapTransform and CacheBackground — on Windows
        # they can trigger very slow repaints and native crashes when zooming
        # or after fit-to-window (cached background pixmaps get high-quality
        # scaled). Plain antialiasing is safe and fast.
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # 2.0: full repaints. With SmartViewportUpdate a click near a support
        # or branch-length number only repainted a small dirty rectangle and
        # the text item could be left blank until the next interaction.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self.setBackgroundBrush(QBrush(QColor("#f7f7f7")))
        # Panning is driven programmatically from the mouse handler (so it can
        # be unbounded), not by the user dragging the bars — hide them. They
        # keep working as the view's scroll position.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Keep the drawing at the top-left instead of centring it: with a
        # scrollable area larger than the viewport the mapping "scroll value ->
        # scene coordinate" stays exact, which free panning relies on.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._pressed = False
        self._dragging = False
        # 1.9: a left press on a movable item (the scale bar) belongs to Qt's
        # item-dragging machinery, not to the free-pan gesture.
        self._item_dragging = False
        # Called once when an item drag ends (cheap bounding-box refresh).
        self.on_item_drag_finished = None
        self._press_pos = None
        self._start_h = 0
        self._start_v = 0
        self._zoom = 1.0

        # Faster item lookup for large scenes (helps hover/selection/zoom).
        try:
            renderer.scene.setItemIndexMethod(
                renderer.scene.ItemIndexMethod.BspTreeIndex
            )
        except Exception:  # noqa: BLE001 - non-fatal optimisation
            pass

    # -- mouse: click-to-select vs drag-to-pan -----------------------------
    def _movable_item_at(self, pos):
        """Topmost movable item under ``pos`` (climb through item groups)."""
        item = self.itemAt(pos.toPoint())
        while item is not None:
            if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
                return item
            item = item.parentItem()
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 1.9: dragging the scale bar is handled by QGraphicsScene. Every
            # other left press starts the (unbounded) pan gesture as before.
            if self._movable_item_at(event.position()) is not None:
                self._item_dragging = True
                self._pressed = False
                self._dragging = False
                super().mousePressEvent(event)
                return
            self._pressed = True
            self._dragging = False
            self._press_pos = event.position()
            self._start_h = self.horizontalScrollBar().value()
            self._start_v = self.verticalScrollBar().value()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._item_dragging:
            super().mouseMoveEvent(event)
            return
        if self._pressed:
            delta = event.position() - self._press_pos
            if not self._dragging and delta.manhattanLength() > QApplication.startDragDistance():
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._dragging:
                self.pan_by_pixels(delta.x(), delta.y())
                event.accept()
                return
        super().mouseMoveEvent(event)

    # -- free panning ------------------------------------------------------
    # The tree can be dragged in *any* direction, without the usual limit of
    # "only inside the scene rectangle": whenever the drag reaches the edge of
    # the scrollable area we extend that area, so the drag never stops.
    def pan_by_pixels(self, dx_px, dy_px):
        # QGraphicsView scroll bars are expressed in *viewport pixels*, so a
        # drag of N pixels is a scroll of N units at any zoom level.
        self._pan_to(self._start_h - dx_px, self._start_v - dy_px)

    def _pan_to(self, want_h, want_v):
        self._grow_scene_for(want_h, want_v)
        self.horizontalScrollBar().setValue(int(round(want_h)))
        self.verticalScrollBar().setValue(int(round(want_v)))

    def _content_rect(self):
        rect = getattr(self._renderer, "content_rect", None)
        if rect is None or not rect.isValid():
            rect = self.scene().sceneRect()
        return rect

    def ensure_pan_room(self):
        """Keep at least one screen of free space around the tree.

        Without this the scrollable area equals the tree itself: right after
        "fit to window" the range collapses to 0 and dragging does nothing at
        all, and when zoomed in the drag stops at the tree's bounding box.
        """
        scene = self.scene()
        if scene is None:
            return
        zoom = self._zoom if self._zoom > 1e-6 else 1.0
        vp = self.viewport().size()
        pad_x = max(vp.width() / zoom, 400.0)
        pad_y = max(vp.height() / zoom, 400.0)
        want = self._content_rect().adjusted(-pad_x, -pad_y, pad_x, pad_y)
        rect = scene.sceneRect()
        if not rect.isValid():
            scene.setSceneRect(want)
        elif not rect.contains(want):
            scene.setSceneRect(rect.united(want))

    def _grow_scene_for(self, want_h, want_v):
        """Extend the scrollable area so ``want_h``/``want_v`` stay reachable.

        Growing the scene rect to the left/top does not move the content: the
        scroll range simply widens while the current scroll value is kept.
        """
        scene = self.scene()
        if scene is None:
            return
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        extra_left = max(0.0, h.minimum() - want_h)
        extra_right = max(0.0, want_h - h.maximum())
        extra_top = max(0.0, v.minimum() - want_v)
        extra_bottom = max(0.0, want_v - v.maximum())
        if not (extra_left or extra_right or extra_top or extra_bottom):
            return
        # Add a comfortable margin so a long drag does not have to grow the
        # rect on every single mouse move. The amounts above are viewport
        # pixels (scroll-bar units); the scene rect works in scene units.
        zoom = self._zoom if self._zoom > 1e-6 else 1.0
        room = max(400.0, self.viewport().width())
        pad_px = max(extra_left, extra_right, extra_top, extra_bottom) + room
        pad = pad_px / zoom
        rect = scene.sceneRect()
        scene.setSceneRect(rect.adjusted(
            -extra_left - (pad if extra_left else 0.0),
            -extra_top - (pad if extra_top else 0.0),
            extra_right + (pad if extra_right else 0.0),
            extra_bottom + (pad if extra_bottom else 0.0),
        ))

    def mouseReleaseEvent(self, event):
        if self._item_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._item_dragging = False
            super().mouseReleaseEvent(event)
            if self.on_item_drag_finished is not None:
                self.on_item_drag_finished()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if self._dragging:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self._dragging = False
                event.accept()
                return
            self._dragging = False
            self._select_at(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _select_at(self, pos):
        # 2.0: walk the whole stack at this point. Support values and branch
        # length numbers are plain text items stacked above the branches; they
        # now map to their node too, so clicking a number selects that branch
        # instead of clearing the selection and leaving the number blank.
        self.scene().clearSelection()
        node = None
        for item in self.items(pos.toPoint()):
            node = self._renderer.node_for_item(item)
            if node is not None:
                break
        if node is not None:
            # select the matching branch item for visual highlight
            branch = self._renderer.node_to_branch.get(node)
            if branch is not None:
                branch.setSelected(True)
            # a collapsed clade is drawn as a triangle instead of branches
            triangle = self._renderer.node_to_collapse.get(node)
            if triangle is not None:
                triangle.setSelected(True)
        self.nodeSelected.emit(node)
        # Force a complete repaint so no text is left out of a dirty region.
        self.viewport().update()

    # -- zoom --------------------------------------------------------------
    def wheelEvent(self, event):
        factor = self.WHEEL_STEP if event.angleDelta().y() > 0 else 1.0 / self.WHEEL_STEP
        self._apply_zoom(factor)
        event.accept()

    def _apply_zoom(self, factor):
        """Zoom by ``factor``, clamped to a safe range to avoid freezes/crashes."""
        new_zoom = self._zoom * factor
        if new_zoom < self.MIN_ZOOM:
            factor = self.MIN_ZOOM / self._zoom
            new_zoom = self.MIN_ZOOM
        elif new_zoom > self.MAX_ZOOM:
            factor = self.MAX_ZOOM / self._zoom
            new_zoom = self.MAX_ZOOM
        if abs(factor - 1.0) < 1e-9:
            return
        self._zoom = new_zoom
        # Widen the scrollable area *before* zooming out, otherwise the scene
        # becomes smaller than the viewport, Qt centres it and the drag jumps.
        self.ensure_pan_room()
        self.scale(factor, factor)

    def zoom_in(self):
        self._apply_zoom(1.25)

    def zoom_out(self):
        self._apply_zoom(0.8)

    def fit_to_window(self):
        # Fit the *tree*, not the (possibly grown) scrollable area: panning
        # extends the scene rect, and fitting that would shrink the tree into
        # the corner every time.
        rect = self._content_rect()
        # Drop the extra room created by panning, then fit the *tree* (not the
        # grown scrollable area) and re-create the panning room for the new
        # zoom level.
        self.scene().setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.ensure_pan_room()

    # -- drag & drop -------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.fileDropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()

    # -- empty-state hint --------------------------------------------------
    def show_empty_hint(self, text):
        # store a hint to draw on the viewport
        self._hint = text
        self.viewport().update()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        hint = getattr(self, "_hint", None)
        if hint:
            painter.setPen(QColor("#999999"))
            painter.setFont(QFont("Sans Serif", 13))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, hint)
