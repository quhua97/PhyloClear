"""Qt graphics items for tree branches and node markers."""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QBrush, QColor, QPainterPath, QPolygonF, QPainter
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
)


class BranchItem(QGraphicsPathItem):
    """An edge connecting a parent node to its child ``node``."""

    HIGHLIGHT_COLOR = "#e74c3c"

    def __init__(self, node, path=None):
        super().__init__(path)
        self.node = node
        self.base_color = "#1f77b4"
        self.base_width = 2.0
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptHoverEvents(True)

    def set_style(self, color, width):
        self.base_color = color
        self.base_width = width
        self._apply_pen()

    def _apply_pen(self):
        if self.isSelected():
            pen = QPen(QColor(self.HIGHLIGHT_COLOR))
            pen.setWidthF(max(self.base_width + 1.5, 3.5))
        else:
            pen = QPen(QColor(self.base_color))
            pen.setWidthF(self.base_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._apply_pen()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        super().hoverEnterEvent(event)
        if not self.isSelected():
            p = QPen(self.pen())
            p.setWidthF(max(p.widthF() + 1.0, 2.5))
            self.setPen(p)

    def hoverLeaveEvent(self, event):
        super().hoverLeaveEvent(event)
        if not self.isSelected():
            self._apply_pen()


class NodeMarkerItem(QGraphicsItem):
    """A small shape marker drawn at a node position."""

    def __init__(self, node, size=5.0, shape="circle"):
        super().__init__()
        self.node = node
        self.size = size
        # NOTE: must NOT be named `shape` — QGraphicsItem already defines a
        # shape() method used for collision/hit-testing; shadowing it with a
        # str breaks hover/zoom (TypeError: 'str' object is not callable).
        self.marker_shape = shape
        self.color = QColor("#333333")
        self.outline = QColor("#111111")
        self.setZValue(2)
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self):
        s = self.size + 4.0
        return QRectF(-s / 2, -s / 2, s, s)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.size
        brush = QBrush(self.color)
        pen = QPen(self.outline)
        pen.setWidthF(1.0)
        painter.setBrush(brush)
        painter.setPen(pen)
        if self.marker_shape == "square":
            painter.drawRect(QRectF(-s / 2, -s / 2, s, s))
        elif self.marker_shape == "triangle":
            poly = QPolygonF([
                QPointF(0, -s / 2),
                QPointF(s / 2, s / 2),
                QPointF(-s / 2, s / 2),
            ])
            painter.drawPolygon(poly)
        else:  # circle
            painter.drawEllipse(QRectF(-s / 2, -s / 2, s, s))

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()


class CollapseTriangleItem(QGraphicsItem):
    """The triangle (wedge) that replaces a collapsed clade.

    The apex sits at the clade's own node position; the base is a vertical
    line at the depth of the deepest tip inside the clade, spanning the clade's
    configured height.
    """

    HIGHLIGHT_COLOR = "#e74c3c"

    def __init__(self, node, triangle, fill="#cccccc", outline="#000000",
                 width=1.0):
        super().__init__()
        self.node = node
        # NOTE: must not be called anything that shadows a QGraphicsItem method
        # (see NodeMarkerItem: `shape` is the classic trap).
        self.triangle = QPolygonF(triangle)
        self.fill = QColor(fill)
        self.outline = QColor(outline)
        self.outline_width = width
        self.setZValue(1.5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptHoverEvents(True)
        self._hovered = False

    def boundingRect(self):
        return self.triangle.boundingRect().adjusted(-3.0, -3.0, 3.0, 3.0)

    def shape(self):
        path = QPainterPath()
        path.addPolygon(self.triangle)
        path.closeSubpath()
        return path

    def set_style(self, fill, outline, width=None):
        self.fill = QColor(fill)
        self.outline = QColor(outline)
        if width is not None:
            self.outline_width = width
        self.update()

    def _pen(self):
        pen = QPen(QColor(self.HIGHLIGHT_COLOR) if self.isSelected() else self.outline)
        pen.setWidthF(max(self.outline_width + (1.5 if self.isSelected() else 0.0),
                          2.0 if self.isSelected() else self.outline_width))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self.fill))
        painter.setPen(self._pen())
        painter.drawPolygon(self.triangle)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        super().hoverEnterEvent(event)
        self._hovered = True
        self.setZValue(2.5)

    def hoverLeaveEvent(self, event):
        super().hoverLeaveEvent(event)
        self._hovered = False
        self.setZValue(1.5)


class AnnotationTextItem(QGraphicsSimpleTextItem):
    """A user-editable annotation label attached to a node."""

    def __init__(self, node, text=""):
        super().__init__(text)
        self.node = node
        self.setZValue(3)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setCursor(Qt.CursorShape.IBeamCursor)


class ScaleBarItem(QGraphicsItemGroup):
    """The scale bar as ONE draggable item (1.9).

    The bar path and its number stay ordinary child items, so all the older
    code that looks for them in the scene keeps working; grouping them merely
    lets the user grab the whole thing and move it. ``on_moved`` receives the
    offset from the automatic bottom-centre position, in scene units.
    """

    def __init__(self, bar, label, base_pos, offset=(0.0, 0.0), on_moved=None):
        super().__init__()
        self._base = QPointF(base_pos)
        self._on_moved = on_moved
        self.setHandlesChildEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(4)
        self.addToGroup(bar)
        self.addToGroup(label)
        self.setPos(QPointF(self._base.x() + float(offset[0]),
                            self._base.y() + float(offset[1])))

    @property
    def base_pos(self):
        return QPointF(self._base)

    def itemChange(self, change, value):
        if (change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
                and self._on_moved is not None):
            point = value
            self._on_moved(point.x() - self._base.x(),
                           point.y() - self._base.y())
        return super().itemChange(change, value)
