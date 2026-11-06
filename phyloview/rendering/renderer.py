"""Scene builder: turns a Tree + TreeLayout + TreeStyle into a QGraphicsScene."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QColor, QPen, QBrush, QPainterPath, QPolygonF
from PySide6.QtWidgets import (QGraphicsScene, QGraphicsPathItem,
                              QGraphicsItem)

from .layout import TreeLayout, RECTANGULAR, CLADOGRAM, RADIAL
from .items import (BranchItem, NodeMarkerItem, AnnotationTextItem,
                    CollapseTriangleItem, ScaleBarItem)


# Short names used when the user asks to label each support value with its
# metric (e.g. "SUP=100/QP-IC=0.761628/LQ-IC=0.692567").
_SUPPORT_SHORT_NAMES = {
    "original": "SUP",
    "s1": "S1", "s2": "S2", "s3": "S3", "s4": "S4", "s5": "S5", "s6": "S6",
}


def _nice_scale(max_len):
    """Return a nice round value <= max_len for the scale bar (e.g. 0.2, 0.5)."""
    if max_len <= 0:
        return None
    exp = math.floor(math.log10(max_len))
    base = 10.0 ** exp
    for m in (5.0, 2.0, 1.0):
        v = m * base
        if v <= max_len:
            return v
    return base


class TreeRenderer:
    """Owns a QGraphicsScene and knows how to rebuild it from a tree."""

    def __init__(self, scene=None):
        self.scene = scene or QGraphicsScene()
        self.tree = None
        self.layout = None
        self.style = None
        # item <-> node mappings
        self.node_to_branch = {}
        self.node_to_marker = {}
        self.node_to_annotation = {}
        self.branch_item_to_node = {}
        self.marker_item_to_node = {}
        self.text_item_to_node = {}
        self.node_to_text = {}
        self.node_to_collapse = {}
        self.collapse_item_to_node = {}
        self.root_stem_item = None
        # 1.9: the scale bar is a single draggable group. ``on_scale_bar_moved``
        # lets the main window mirror the new offset into the style panel.
        self.scale_bar_item = None
        self.on_scale_bar_moved = None
        # Optional :class:`~phyloview.annotations.LabelAnnotations`: when set,
        # tip labels are replaced by the matching row of the imported table.
        self.annotations = None
        # coordinate transform parameters
        self._x_scale = 1.0
        self._y_scale = 1.0
        self._ox = 0.0
        self._oy = 0.0
        self._center = QPointF(0, 0)
        self._radius_scale = 1.0
        self.scene_rect = QRectF(0, 0, 800, 600)
        # Tight bounding box of the tree drawing (set in rebuild()); used by
        # "fit to window" because sceneRect may be grown by free panning.
        self.content_rect = QRectF(0, 0, 800, 600)

    # -- visibility (collapse) ---------------------------------------------
    def _visible(self, node):
        """False for nodes hidden inside a collapsed clade."""
        visible = getattr(self.layout, "visible", None)
        return True if visible is None else node in visible

    # -- coordinate mapping -------------------------------------------------
    def _map(self, x, y):
        if self.layout and self.layout.mode == RADIAL:
            return QPointF(
                self._center.x() + x * self._radius_scale,
                self._center.y() + y * self._radius_scale,
            )
        return QPointF(
            self._ox + x * self._x_scale,
            self._oy + y * self._y_scale,
        )

    def node_pos(self, node):
        return self._map(node.x, node.y)

    # -- label annotations (1.5) -------------------------------------------
    def display_name(self, node):
        """The text drawn for a tip: the annotation row if there is one.

        FigTree keeps the original label whenever a table has no matching row,
        so unmatched tips simply keep the name read from the tree file.
        """
        base = node.name or ""
        if self.annotations is None:
            return base
        try:
            text = self.annotations.label_for(node.name)
        except Exception:  # noqa: BLE001 - a broken table must never break drawing
            return base
        return base if text is None else text

    # -- main rebuild -------------------------------------------------------
    def rebuild(self, tree, style):
        self.tree = tree
        self.style = style
        self.scene.clear()
        self.node_to_branch = {}
        self.node_to_marker = {}
        self.node_to_annotation = {}
        self.branch_item_to_node = {}
        self.marker_item_to_node = {}
        self.text_item_to_node = {}
        self.node_to_text = {}
        self.node_to_collapse = {}
        self.collapse_item_to_node = {}
        self.root_stem_item = None
        self.scale_bar_item = None

        self.layout = TreeLayout(tree, style.layout_mode,
                                 collapse_height=style.collapse_height)
        self.layout.compute()
        self._compute_transform()

        self.scene.setBackgroundBrush(QBrush(QColor(style.background_color)))

        for node in tree.nodes:
            if node.is_root or not self._visible(node):
                continue
            self._add_branch(node)
        self._add_root_stem()
        for node in tree.nodes:
            if not self._visible(node):
                continue
            self._add_collapsed_triangle(node)
        for node in tree.nodes:
            if not self._visible(node):
                continue
            self._add_marker(node)
        for node in tree.nodes:
            if not self._visible(node):
                continue
            if node.is_leaf:
                self._add_leaf_label(node)
            elif node.collapsed:
                self._add_collapse_label(node)
            else:
                self._add_support_label(node)
                self._add_branch_length_labels(node)
        for node in tree.nodes:
            if node.annotations.get("annotation") and self._visible(node):
                self._add_annotation_item(node)

        self._add_scale_bar()

        # Finalise the scene rect from the real extent of every item (branches,
        # labels, scale bar, annotations). This guarantees that after zooming in
        # the user can pan to — and "Fit to Window" can show — the *whole* tree,
        # including tip labels that extend past the layout estimate.
        rect = self.scene.itemsBoundingRect()
        if rect.isValid():
            rect = rect.adjusted(-24.0, -24.0, 24.0, 24.0)
            # content_rect = the tight extent of the drawing. The canvas may
            # grow the scene rect beyond it while panning, so "fit to window"
            # and the scale-bar maths use this rect instead of sceneRect().
            self.content_rect = rect
            self.scene.setSceneRect(rect)

    def _compute_transform(self):
        tree = self.tree
        layout = self.layout
        mode = layout.mode
        if mode == RADIAL:
            radius = 260.0
            self._radius_scale = radius
            self._center = QPointF(radius + 60, radius + 60)
            self.scene_rect = QRectF(0, 0, radius * 2 + 120, radius * 2 + 120)
        else:
            margin = 50.0
            leaf_spacing = 24.0
            self._y_scale = leaf_spacing * self.style.vertical_stretch
            if mode == CLADOGRAM:
                self._x_scale = 48.0 * self.style.horizontal_stretch
            else:
                target_width = 720.0
                self._x_scale = target_width / max(layout.width, 1e-6)
                self._x_scale = max(15.0, min(self._x_scale, 500.0))
                self._x_scale *= self.style.horizontal_stretch
            self._ox = margin
            self._oy = margin
            w = margin * 2 + layout.width * self._x_scale
            h = margin * 2 + layout.height * self._y_scale
            if self._scale_bar_wanted():
                h += 36.0
            self.scene_rect = QRectF(0, 0, max(w, 400), max(h, 300))
        # NOTE: the final scene rect is set in rebuild() from the *actual*
        # items bounding box so that tip labels, the scale bar and any
        # annotations that overflow the layout estimate stay reachable when
        # panning / fitting. We only keep self.scene_rect here for the scale
        # bar's centring maths.

    # -- item builders ------------------------------------------------------
    def _add_branch(self, node):
        parent = node.parent
        path = QPainterPath()
        if self.layout.mode == RADIAL:
            path = self._radial_branch_path(parent, node)
        else:
            p1 = self.node_pos(parent)
            p2 = self.node_pos(node)
            # Rectangular layout: the vertical connector between sibling
            # branches must sit at the PARENT's x (i.e. the node position), so
            # that the up and down branches emanate from the node/red marker and
            # align exactly on it. Each child then has a horizontal segment at
            # its own y carrying the branch length.
            mid = QPointF(p1.x(), p2.y())
            path.moveTo(p1)
            path.lineTo(mid)
            path.lineTo(p2)
        item = BranchItem(node, path)
        item.set_style(
            self.style.branch_color_for(node),
            self.style.branch_width_for(node),
        )
        item.setZValue(1)
        self.scene.addItem(item)
        self.node_to_branch[node] = item
        self.branch_item_to_node[item] = node

    def _add_root_stem(self):
        """Draw the root stem: the branch drawn to the left of the root.

        Its length is ``style.root_length``, expressed in the same units as the
        branch lengths, so it grows with the horizontal stretch exactly like
        every other branch and stays consistent with the scale bar.
        """
        if self.style.root_length <= 0.0 or self.tree is None:
            return
        root = self.tree.root
        if root is None or self.layout.mode == RADIAL:
            return
        length_px = self.style.root_length * self._x_scale
        if length_px <= 0.0:
            return
        p = self.node_pos(root)
        path = QPainterPath()
        path.moveTo(p.x() - length_px, p.y())
        path.lineTo(p.x(), p.y())
        item = QGraphicsPathItem(path)
        pen = QPen(QColor(self.style.branch_color))
        pen.setWidthF(self.style.branch_width)
        item.setPen(pen)
        item.setZValue(1)
        self.scene.addItem(item)
        self.root_stem_item = item

    def _radial_branch_path(self, parent, child):
        """Curved radial branch: a radial segment + a circular arc."""
        p = self.node_pos(parent)
        c = self.node_pos(child)
        cx, cy = self._center.x(), self._center.y()
        vpx, vpy = p.x() - cx, p.y() - cy
        vcx, vcy = c.x() - cx, c.y() - cy
        r_p = math.hypot(vpx, vpy)
        r_c = math.hypot(vcx, vcy)
        th_p = math.atan2(vpy, vpx)
        th_c = math.atan2(vcy, vcx)

        path = QPainterPath()
        path.moveTo(p)
        if r_p < 1e-6:
            # parent is the root (at center): radiate straight to the child
            path.lineTo(c)
            return path

        # radial segment outward to the child's radius at the parent's angle
        path.lineTo(cx + r_c * math.cos(th_p), cy + r_c * math.sin(th_p))

        # circular arc from parent angle to child angle at the child's radius
        delta = (th_c - th_p + math.pi) % (2.0 * math.pi) - math.pi
        steps = max(2, int(abs(delta) / (math.pi / 24.0)) + 1)
        for i in range(1, steps + 1):
            a = th_p + delta * i / steps
            path.lineTo(cx + r_c * math.cos(a), cy + r_c * math.sin(a))
        return path

    # -- collapsed clades ---------------------------------------------------
    # "Collapse / expand — collapse clades to triangles with configurable
    # height and labels": the clade is replaced by a triangle whose apex is the
    # clade's own node, whose base sits at the depth of its deepest tip, and
    # whose vertical height is ``style.collapse_height`` tip spacings (0 =
    # automatic: the span of the tips it replaces).
    def collapse_tip_x(self, node):
        """Scene x of the deepest tip inside this clade."""
        deepest = max(n.x for n in node.iter_nodes())
        return self._ox + deepest * self._x_scale

    def collapse_triangle_polygon(self, node, min_width=8.0):
        apex = self.node_pos(node)
        base_x = max(self.collapse_tip_x(node), apex.x() + min_width)
        half = max(self.layout.rows_for(node), 1.0) * self._y_scale / 2.0
        return QPolygonF([
            QPointF(apex.x(), apex.y()),
            QPointF(base_x, apex.y() - half),
            QPointF(base_x, apex.y() + half),
        ])

    def collapse_label_text(self, node):
        """Text printed next to a collapsed clade's triangle."""
        if node.collapse_label:
            return str(node.collapse_label)
        return self.display_name(node)

    def _add_collapsed_triangle(self, node):
        if node is None or node.is_leaf or not node.collapsed:
            return
        if self.tree is None or self.tree.root is None:
            return
        if self.layout.mode == RADIAL:
            # Triangles belong to the horizontal layouts. In the radial layout
            # the collapsed clade already behaves as one terminal unit, so it
            # simply becomes a single branch reaching the outer circle.
            return
        item = CollapseTriangleItem(
            node,
            self.collapse_triangle_polygon(node),
            fill=node.style.get("collapse_fill", self.style.collapse_fill_color),
            outline=self.style.branch_color_for(node),
            width=self.style.branch_width_for(node),
        )
        self.scene.addItem(item)
        self.node_to_collapse[node] = item
        self.collapse_item_to_node[item] = node

    def _add_collapse_label(self, node):
        """Label of a collapsed clade (drawn where its tips would have been)."""
        if not self.style.show_leaf_labels:
            return
        text = self.collapse_label_text(node)
        if not text:
            return
        item = self.scene.addText(text, self._label_font(
            self.style.label_font_size, self.style.label_bold,
            self.style.label_italic))
        item.setDefaultTextColor(QColor(self.style.label_color_for(node)))
        item.setZValue(3)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        height = item.boundingRect().height()
        if self.layout.mode == RADIAL:
            item.setPos(self.node_pos(node) + self._radial_label_offset(node))
        else:
            tri = self.node_to_collapse.get(node)
            if tri is None:
                pos = self.node_pos(node)
                item.setPos(pos.x() + 6.0, pos.y() - height / 2.0)
            else:
                box = tri.triangle.boundingRect()
                item.setPos(box.right() + 6.0,
                            box.center().y() - height / 2.0)
        self.text_item_to_node[item] = node
        self.node_to_text.setdefault(node, []).append(item)

    def _add_marker(self, node):
        if not self.style.show_node_markers:
            return
        # Only internal nodes (branching points, including the root but not
        # leaves) carry a marker, per the user's definition of "internal node".
        if not node.is_internal:
            return
        pos = self.node_pos(node)
        marker = NodeMarkerItem(node, self.style.node_size, self.style.node_shape)
        marker.color = QColor(node.style.get("marker_color", self.style.node_color))
        marker.outline = QColor(self.style.node_outline)
        marker.setPos(pos)
        self.scene.addItem(marker)
        self.node_to_marker[node] = marker
        self.marker_item_to_node[marker] = node

    def _label_font(self, size, bold=False, italic=False):
        font = QFont(self.style.label_font_family)
        font.setPointSizeF(size)
        font.setBold(bold)
        font.setItalic(italic)
        return font

    def _add_leaf_label(self, node):
        if not self.style.show_leaf_labels:
            return
        name = self.display_name(node)
        font = self._label_font(
            self.style.label_font_size, self.style.label_bold,
            self.style.label_italic)
        item = self.scene.addText(name, font)
        item.setDefaultTextColor(QColor(self.style.label_color_for(node)))
        runs = self._label_runs(node)
        if runs is not None:
            # The sheet supplies its own emphasis (bold / italic / colour);
            # everything else — size included — still comes from the style.
            item.setHtml(self._label_html(
                runs, self.style.label_color_for(node)))
        item.setZValue(3)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        pos = self.node_pos(node)
        if self.layout.mode == RADIAL:
            offset = self._radial_label_offset(node)
        else:
            # Vertically center the label on the tip so it sits flush with
            # the terminal branch (matching FigTree's tip-label alignment).
            offset = QPointF(6.0, -item.boundingRect().height() / 2.0)
        item.setPos(pos + offset)
        self.text_item_to_node[item] = node
        self.node_to_text.setdefault(node, []).append(item)

    def _radial_label_offset(self, node):
        dx, dy = node.x, node.y
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return QPointF(6, 0)
        return QPointF(dx / length * 6.0, dy / length * 6.0)

    # -- label formatting taken from the spreadsheet (1.6) -----------------
    def _label_runs(self, node):
        """``[(text, fmt)]`` from the annotation table, or ``None``."""
        if self.annotations is None:
            return None
        getter = getattr(self.annotations, "runs_for", None)
        if getter is None:
            return None
        if not getattr(self.annotations, "sync_format", True):
            return None
        return getter(node.name)

    @staticmethod
    def _escape_html(text):
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _label_html(self, runs, base_color):
        """Rich text for one tip: sheet emphasis on top of the software style."""
        pieces = []
        for text, fmt in runs:
            if not text:
                continue
            fmt = fmt or {}
            bold = bool(self.style.label_bold or fmt.get("bold"))
            italic = bool(self.style.label_italic or fmt.get("italic"))
            color = fmt.get("color") or base_color
            attrs = []
            if bold:
                attrs.append("font-weight:600")
            if italic:
                attrs.append("font-style:italic")
            if color:
                attrs.append("color:" + str(color))
            body = self._escape_html(text)
            if attrs:
                body = '<span style="%s">%s</span>' % (";".join(attrs), body)
            pieces.append(body)
        head = "font-family:'%s';font-size:%gpt" % (
            self.style.label_font_family, self.style.label_font_size)
        if base_color:
            head += ";color:%s" % base_color
        return '<span style="%s">%s</span>' % (head, "".join(pieces))

    def _make_value_click_through(self, item, node):
        """Support / branch-length numbers are labels, not widgets (2.0).

        Left-clicking one of these numbers used to make it disappear: Qt
        repainted only the dirty rectangle of a text item that was still in
        the mouse/selection machinery. Make the number ignore mouse events,
        disable the extended-style-option clipping, and register it so a
        click still selects the branch the number belongs to.
        """
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, False)
        item.setAcceptedMouseButtons(Qt.MouseButtons(Qt.MouseButton.NoButton))
        self.text_item_to_node[item] = node

    def _add_support_label(self, node):
        if not self.style.show_support:
            return
        text = self._support_text(node)
        if not text:
            return
        item = self.scene.addText(text, self._label_font(self.style.support_font_size))
        item.setDefaultTextColor(QColor(self.style.support_color))
        item.setZValue(3)
        self._make_value_click_through(item, node)
        pos = self.node_pos(node)
        box = item.boundingRect()
        above = (
            self.layout.mode != RADIAL
            and not node.is_root
            and getattr(self.style, "support_position", "above_branch")
            == "above_branch"
        )
        if above:
            # 1.9: the value belongs ABOVE the horizontal branch that leads
            # into this branching point, right-aligned to the point itself.
            # That is exactly the red box in the user's sketch. A couple of
            # pixels of clearance keep it off the branch line and the vertical
            # connector. The root has no incoming branch, so it keeps the old
            # placement below the node.
            offset = QPointF(-box.width() - 4.0, -box.height() - 2.0)
        else:
            offset = QPointF(
                -self.style.support_font_size * len(text) * 0.28, 4.0)
        item.setPos(pos + offset)
        item.setToolTip(text)

    def _support_text(self, node):
        """Compose the label from the support metrics the user selected.

        * QuartetScores: "original" (the number in front of the colon) plus
          qp-ic / lq-ic / eqp-ic from the square-bracket comment.
        * IQ-TREE: s1 / s2 are the two numbers around the "/".
        * A plain tree keeps behaving exactly as before.
        Several metrics are joined with "/" as in the original files.
        """
        fields = getattr(self.style, "support_fields", None)
        metrics = getattr(node, "support_metrics", None) or {}
        if fields is not None:
            # Metrics actually present on this node and selected for display.
            present = [key for key in fields if key in metrics]
            parts = []
            show_names = bool(getattr(self.style, "support_show_names", False))
            hide_enabled = bool(getattr(self.style,
                                        "support_hide_below_enabled", False))
            thresholds = getattr(self.style, "support_hide_thresholds", None) or {}
            multi = len(present) >= 2
            for key in present:
                if hide_enabled and key in thresholds:
                    thr = thresholds[key]
                    if thr is not None:
                        num = self._support_value_as_float(metrics[key])
                        if num is not None and num < thr:
                            # Below the per-metric threshold.
                            # With two or more metrics shown, keep the slot as
                            # "-" so the remaining metrics stay aligned; with a
                            # single metric, simply omit it (no dash).
                            if multi:
                                parts.append("-")
                            continue
                value = self._format_support(metrics[key])
                if show_names:
                    name = _SUPPORT_SHORT_NAMES.get(key, key.upper())
                    value = "%s=%s" % (name, value)
                parts.append(value)
            return "/".join(parts)
        # Not configured (e.g. a renderer used stand-alone): old behaviour.
        if node.support is None:
            return ""
        return self._format_support(node.support)

    def _format_support(self, value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            d = max(0, int(getattr(self.style, "support_decimals", 6)))
            text = "%.*f" % (d, value)
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return text or "0"
        return str(value)

    def _support_value_as_float(self, value):
        """Best-effort conversion of a support metric to a float.

        Returns ``None`` when the value is not numeric, so a non-numeric
        support value is always kept and never hidden by the threshold.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except (ValueError, TypeError):
            return None

    def _add_branch_length_labels(self, node):
        if not self.style.show_branch_lengths:
            return
        for child in node.children:
            if child.branch_length is None:
                continue
            p1 = self.node_pos(node)
            p2 = self.node_pos(child)
            if self.layout.mode == RADIAL:
                # place at the midpoint of the branch (a radial segment/arc)
                mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            else:
                # rectangular/cladogram: the horizontal (length-carrying)
                # segment now runs at the child's y, so place the label on it.
                mid = QPointF((p1.x() + p2.x()) / 2, p2.y() - 4.0)
            text = f"{child.branch_length:.4g}"
            item = self.scene.addText(text, self._label_font(self.style.branch_length_font_size))
            item.setDefaultTextColor(QColor(self.style.branch_length_color))
            item.setZValue(3)
            self._make_value_click_through(item, child)
            item.setPos(mid)

    def _add_annotation_item(self, node):
        text = node.annotations.get("annotation", "")
        item = AnnotationTextItem(node, text)
        item.setFont(self._label_font(self.style.label_font_size, italic=True))
        item.setBrush(QColor(node.style.get("annotation_color", "#e67e22")))
        pos = self.node_pos(node)
        item.setPos(pos + QPointF(0.0, -self.style.label_font_size * 1.5))
        self.scene.addItem(item)
        self.node_to_annotation[node] = item

    # -- scale bar ---------------------------------------------------------
    def _has_branch_lengths(self):
        for node in self.tree.nodes:
            if not node.is_root and node.branch_length is not None:
                return True
        return False

    def _max_root_to_tip(self):
        def rec(node, acc):
            if node.is_leaf:
                return acc
            best = 0.0
            for c in node.children:
                bl = c.branch_length if c.branch_length else 0.0
                best = max(best, rec(c, acc + bl))
            return best

        return rec(self.tree.root, 0.0)

    def _scale_bar_wanted(self):
        # The scale bar is independent of the per-branch length numbers:
        # FigTree shows the scale bar even when individual branch lengths
        # are not printed.
        return (
            self.style.show_scale_bar
            and self._has_branch_lengths()
            and self.layout.mode != RADIAL
        )

    def _scale_bar_length(self):
        """Length in branch-length units; ``None`` when it cannot be drawn.

        A value typed in the panel wins; 0 (the default) keeps the old
        "nicest round number below the longest root-to-tip path" behaviour.
        """
        manual = float(getattr(self.style, "scale_bar_length", 0.0) or 0.0)
        if manual > 0.0:
            return manual, True
        value = _nice_scale(self._max_root_to_tip())
        return (None if value is None else value), False

    def _add_scale_bar(self):
        if not self._scale_bar_wanted():
            return
        value, manual = self._scale_bar_length()
        if value is None or value <= 0.0:
            return
        # px_per_unit is the horizontal scale for both rectangular and
        # cladogram layouts (it already contains the horizontal stretch), so
        # the bar grows with the branches as the user stretches the tree.
        length_px = value * self._x_scale
        minimum = 1.0 if manual else 20.0
        if length_px < minimum:
            return

        # Default position: horizontally centred, just below the tree.
        y = self._oy + self.layout.height * self._y_scale + 22.0
        x = (self.scene_rect.width() - length_px) / 2.0
        base = QPointF(x, y)

        # Children use coordinates relative to the group origin; the group
        # itself is placed (and dragged) in scene coordinates.
        path = QPainterPath()
        path.moveTo(0.0, 0.0)
        path.lineTo(length_px, 0.0)
        path.moveTo(0.0, -3.0)
        path.lineTo(0.0, 3.0)
        path.moveTo(length_px, -3.0)
        path.lineTo(length_px, 3.0)
        bar = QGraphicsPathItem(path)
        pen = QPen(QColor(self.style.branch_length_color))
        pen.setWidthF(1.2)
        bar.setPen(pen)
        bar.setZValue(4)
        self.scene.addItem(bar)

        text = "%.4g" % value
        label = self.scene.addText(
            text, self._label_font(self.style.branch_length_font_size)
        )
        label.setDefaultTextColor(QColor(self.style.branch_length_color))
        label.setZValue(4)
        label.setPos(length_px / 2.0 - label.boundingRect().width() / 2.0,
                     4.0)

        offset = (float(getattr(self.style, "scale_bar_offset_x", 0.0) or 0.0),
                  float(getattr(self.style, "scale_bar_offset_y", 0.0) or 0.0))
        self.scale_bar_item = ScaleBarItem(
            bar, label, base, offset=offset,
            on_moved=self._on_scale_bar_moved)
        self.scale_bar_item.setToolTip(
            "Drag to move the scale bar")
        self.scene.addItem(self.scale_bar_item)

    def _on_scale_bar_moved(self, dx, dy):
        """Keep the dragged position across later rebuilds and exports."""
        self.style.scale_bar_offset_x = dx
        self.style.scale_bar_offset_y = dy
        if self.on_scale_bar_moved is not None:
            self.on_scale_bar_moved(dx, dy)

    # -- selection helpers --------------------------------------------------
    def node_for_item(self, item):
        if isinstance(item, BranchItem):
            return self.branch_item_to_node.get(item)
        if isinstance(item, NodeMarkerItem):
            return self.marker_item_to_node.get(item)
        if isinstance(item, CollapseTriangleItem):
            return self.collapse_item_to_node.get(item)
        if isinstance(item, AnnotationTextItem):
            return item.node
        return self.text_item_to_node.get(item)

    def apply_style_to_node(self, node):
        """Refresh a single node's branch/marker color after a style edit."""
        branch = self.node_to_branch.get(node)
        if branch:
            branch.set_style(
                self.style.branch_color_for(node),
                self.style.branch_width_for(node),
            )
        marker = self.node_to_marker.get(node)
        if marker:
            marker.color = QColor(node.style.get("marker_color", self.style.node_color))
            marker.update()
        triangle = self.node_to_collapse.get(node)
        if triangle:
            triangle.set_style(
                node.style.get("collapse_fill", self.style.collapse_fill_color),
                self.style.branch_color_for(node),
                self.style.branch_width_for(node),
            )
