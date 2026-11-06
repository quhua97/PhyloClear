"""Style editing panel (dock widget) for branches, nodes and annotations.

All controls apply their changes immediately (live refresh) — there is no
separate "Apply" button.
"""

import os

from PySide6.QtCore import Qt, Signal, QObject, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QFormLayout,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QAbstractSpinBox,
    QSlider,
    QCheckBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QColorDialog,
    QScrollArea,
    QFrame,
)


class _NoWheelFilter(QObject):
    """Block the mouse wheel from changing spin-box / combo-box values.

    Numbers (width, font size, size, stretch, layout choice, node shape) must
    be adjusted with the arrows or the keyboard, never by scrolling over them.
    Wheel events on the canvas (zoom) are unaffected because that widget is
    not a child of this panel.

    The wheel is *not* swallowed silently: scrolling over a numeric control
    scrolls the panel instead, so a long panel stays navigable.
    """

    def __init__(self, scroller=None, parent=None):
        super().__init__(parent)
        self._scroller = scroller

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Wheel
                and isinstance(obj, (QAbstractSpinBox, QComboBox, QSlider))):
            # 2.1: the new sliders must behave like the spin boxes — a wheel
            # scrolls the panel, it never nudges the value.
            self._scroll_panel(event)
            return True
        return False

    def _scroll_panel(self, event):
        if self._scroller is None:
            return
        bar = self._scroller.verticalScrollBar()
        if bar is None:
            return
        delta = event.angleDelta().y()
        if delta:
            bar.setValue(bar.value() - delta)


# English strings used by QColorDialog's own (non-native) widgets.  Qt builds
# these labels in C++ and never runs them through our Translator, so 0.01
# translates them explicitly; see :func:`localize_color_dialog`.
COLOR_DIALOG_STRINGS = (
    "Select Color",
    "&Basic colors", "&Custom colors", "Hu&e:", "&Sat:", "&Val:",
    "&Red:", "&Green:", "Bl&ue:", "A&lpha channel:", "&HTML:",
    "&Pick Screen Color", "&Add to Custom Colors", "OK", "Cancel",
)


def localize_color_dialog(dialog, tr):
    """Make Qt's colour picker follow the application language (0.01).

    ``QColorDialog.getColor`` opens the *native* Windows dialog whose buttons
    and labels are always in the OS language, even when the UI is Chinese.
    Forcing the Qt implementation and translating its child widgets fixes it.
    """
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.setWindowTitle(tr("Select Color"))
    # Standard buttons first — the generic pass below only recognises the
    # original English texts, so OK/Cancel must be handled before that.
    for box in dialog.findChildren(QDialogButtonBox):
        for button in box.buttons():
            role = box.standardButton(button)
            if role == QDialogButtonBox.StandardButton.Ok:
                button.setText(tr("OK"))
            elif role == QDialogButtonBox.StandardButton.Cancel:
                button.setText(tr("Cancel"))
            elif role == QDialogButtonBox.StandardButton.Reset:
                button.setText(tr("Reset"))
    for cls in (QLabel, QPushButton, QCheckBox, QGroupBox):
        for widget in dialog.findChildren(cls):
            if not hasattr(widget, "text"):
                continue
            source = widget.text()
            if source not in COLOR_DIALOG_STRINGS:
                continue
            translated = tr(source)
            if translated != source:
                # Chinese labels do not need Qt's '&' mnemonic; keeping it
                # would underline a CJK character.
                widget.setText(translated.lstrip("&"))


class ColorButton(QPushButton):
    """A button that shows a color swatch and opens a localized color dialog."""

    colorChanged = Signal(str)

    def __init__(self, color="#1f77b4", translator=None):
        super().__init__()
        self._translator = translator
        self._color = QColor(color)
        self.setFixedWidth(64)
        self.clicked.connect(self._pick)
        self._refresh()

    def _t(self, source):
        return self._translator.tr(source) if self._translator else source

    def set_translator(self, translator):
        self._translator = translator
        
    def _refresh(self):
        self.setStyleSheet(
            "QPushButton { background-color: %s; border: 1px solid #888; border-radius: 3px; }"
            % self._color.name()
        )

    def _pick(self):
        dialog = QColorDialog(self._color, self)
        localize_color_dialog(dialog, self._t)
        if dialog.exec():
            c = dialog.currentColor()
            if c.isValid():
                self.set_color(c.name())

    def set_color(self, hex_color):
        self._color = QColor(hex_color)
        self._refresh()
        self.colorChanged.emit(self._color.name())

    def color(self):
        return self._color.name()


class StylePanel(QWidget):
    """Collects style edits and emits them via plain callbacks (live)."""

    def __init__(self, style, translator, parent=None):
        super().__init__(parent)
        self.style = style
        self.translator = translator
        self._t = translator.tr
        self.selected_node = None
        self.on_style_change = None    # (dict) -> None   — any control changed
        self.on_layout_change = None   # (mode) -> None
        self.on_stretch = None         # () -> None       — horizontal/vertical stretch
        self.on_branch_order = None    # (mode) -> None   — clade ordering by size
        self.on_root_branch = None     # (node) -> None   — reroot on the selected clade's branch
        self.on_midpoint_root = None   # () -> None       — midpoint rooting
        self.on_rotate = None          # (node) -> None   — flip node / subtrees
        self.on_collapse = None        # (node) -> None   — collapse clade to a triangle
        self.on_expand = None          # (node) -> None   — expand a collapsed clade
        self.on_expand_all = None      # () -> None       — expand every collapsed clade
        self.on_collapse_label = None  # (node, text) -> None
        # label annotations (1.5) — replace tip labels from a spreadsheet
        self.on_import_table = None    # () -> None      — open a file dialog
        self.on_reload_table = None    # () -> None      — re-read the file
        self.on_clear_table = None     # () -> None      — drop the table
        self.on_auto_sync = None       # (bool) -> None  — watch file changes
        self.on_has_header = None      # (bool) -> None  — first row is a header
        self.on_sheet = None           # (name) -> None  — pick another sheet
        self.on_columns = None         # ([int]) -> None — columns to show
        self.on_separator = None       # (str) -> None   — join separator
        # label formatting (1.6) — bold / italic / colour from the sheet
        self.on_sync_format = None     # (bool) -> None  — copy cell emphasis
        self._translatable = []        # (widget_or_setter, source_key)
        # 2.1: every numeric control is a slider + spin box pair. The spin box
        # remains the public attribute (setValue still works from the outside),
        # while the slider is the quick way to scrub a value.
        self._slider_pairs = []        # (QSlider, spin box, factor)
        self._slider_syncing = False
        # The scale bar has no numeric offset controls any more (2.1); this
        # mirrors the latest drag so the value can be persisted with settings.
        self._scale_bar_offset = (0.0, 0.0)
        # Guard flag: True while we fill the annotation controls ourselves, so
        # the "changed" handlers do not fire back at the model.
        self._populating = False
        self._annotations = None
        self._annot_matched = 0
        self._annot_total = 0
        # 1.8: the support-value checkboxes are rebuilt for each tree, since
        # a QuartetScores file and an IQ-TREE file expose different metrics.
        self._support_field_specs = []
        self.support_field_checks = []
        # All groups live in an inner container that is placed inside a scroll
        # area: the panel is taller than a typical window, so without this the
        # bottom groups (View / Tree Operations) were clipped and unreachable.
        self._content = QWidget(self)
        self._build()
        self._connect_live()
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidget(self._content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)
        # Forbid the scroll wheel from nudging any numeric / combo control.
        # Install on the panel (catches descendant events) and on each
        # individual control as a guaranteed backstop.
        self._no_wheel_filter = _NoWheelFilter(self._scroll, self)
        self.installEventFilter(self._no_wheel_filter)
        for w in self.findChildren(QAbstractSpinBox):
            w.installEventFilter(self._no_wheel_filter)
        for w in self.findChildren(QComboBox):
            w.installEventFilter(self._no_wheel_filter)
        for w in self.findChildren(QSlider):
            w.installEventFilter(self._no_wheel_filter)

    # -- small helpers -----------------------------------------------------
    def _reg(self, setter, source_key):
        self._translatable.append((setter, source_key))

    def _label(self, source_key):
        lbl = QLabel()
        self._reg(lbl.setText, source_key)
        lbl.setText(self._t(source_key))
        return lbl

    def _group(self, source_key):
        g = QGroupBox()
        self._reg(g.setTitle, source_key)
        g.setTitle(self._t(source_key))
        return g

    def _check_group(self, source_key, checked):
        """A group box whose own title-line checkbox toggles the whole feature.

        The "show X" switch is the group box itself: it is drawn on the frame
        line together with the title, so there is no separate checkbox row.
        Unchecking also disables the group's inner controls, which is exactly
        the semantics we want (no markers -> shape/size are irrelevant).
        """
        g = self._group(source_key)
        g.setCheckable(True)
        g.setChecked(bool(checked))
        return g

    def _btn(self, source_key):
        b = QPushButton()
        self._reg(b.setText, source_key)
        b.setText(self._t(source_key))
        return b

    def _check(self, source_key):
        c = QCheckBox()
        self._reg(c.setText, source_key)
        c.setText(self._t(source_key))
        return c

    # -- 2.1: slider + spin box for every numeric setting ------------------
    @staticmethod
    def _slider_factor(spin):
        """Integer ticks per display unit for a QDoubleSpinBox.

        QSlider only knows integers, so 0.01 units become 1 tick. Very wide
        ranges (root length 0..1000, scale-bar length 0..1e6) gradually give
        up decimal resolution instead of creating millions of ticks; the spin
        box on the right always keeps full precision.
        """
        decimals = spin.decimals() if isinstance(spin, QDoubleSpinBox) else 0
        factor = 10 ** min(int(decimals), 6)
        span = spin.maximum() - spin.minimum()
        while factor > 1 and span * factor > 200000:
            factor //= 10
        return factor

    def _slider_row(self, spin, width=92):
        """Slider on the left, the original numeric box on the right."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        slider = QSlider(Qt.Orientation.Horizontal, holder)
        factor = self._slider_factor(spin)
        slider.setRange(int(round(spin.minimum() * factor)),
                        int(round(spin.maximum() * factor)))
        step = max(1, int(round(spin.singleStep() * factor)))
        slider.setSingleStep(step)
        slider.setPageStep(max(step, step * 10))
        slider.setValue(int(round(spin.value() * factor)))
        slider.setMinimumWidth(80)
        spin.setFixedWidth(width)
        row.addWidget(slider, 1)
        row.addWidget(spin, 0)
        self._slider_pairs.append((slider, spin, factor))
        # Two-way binding. Setting the spin box still runs the ordinary
        # "valueChanged -> style changed" path, so a slider scrub redraws the
        # tree exactly like typing a number does.
        slider.valueChanged.connect(
            lambda value, s=spin, f=factor: self._slider_to_spin(value, s, f))
        spin.valueChanged.connect(
            lambda value, sl=slider, f=factor: self._spin_to_slider(value, sl, f))
        return holder

    def _slider_to_spin(self, value, spin, factor):
        if self._slider_syncing:
            return
        target = value / factor
        if abs(spin.value() - target) < 1e-9:
            return
        self._slider_syncing = True
        try:
            spin.setValue(target)
        finally:
            self._slider_syncing = False

    def _spin_to_slider(self, value, slider, factor):
        if self._slider_syncing:
            return
        target = max(slider.minimum(),
                     min(slider.maximum(), int(round(value * factor))))
        if slider.value() == target:
            return
        self._slider_syncing = True
        try:
            slider.setValue(target)
        finally:
            self._slider_syncing = False

    def _sync_all_sliders(self):
        for slider, spin, factor in self._slider_pairs:
            target = max(slider.minimum(),
                         min(slider.maximum(), int(round(spin.value() * factor))))
            slider.blockSignals(True)
            slider.setValue(target)
            slider.blockSignals(False)

    def sync_from_style(self):
        """Mirror ``self.style`` into all controls, without emitting signals.

        Used when a saved settings file is loaded (2.1). Blocking the signals
        is essential: otherwise each setValue would enqueue a stale style
        update that overwrites the settings we are restoring.
        """
        s = self.style

        def _spin(widget, value):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        def _combo(widget, key):
            idx = widget.findData(key)
            if idx >= 0:
                widget.blockSignals(True)
                widget.setCurrentIndex(idx)
                widget.blockSignals(False)

        _combo(self.layout_combo, s.layout_mode)
        _combo(self.branch_order_combo, s.branch_order)
        _combo(self.node_shape, s.node_shape)
        for widget, value in (
            (self.h_stretch, s.horizontal_stretch),
            (self.v_stretch, s.vertical_stretch),
            (self.root_length, s.root_length),
            (self.collapse_height, s.collapse_height),
            (self.branch_width, s.branch_width),
            (self.scale_length, s.scale_bar_length),
            (self.bl_font_size, s.branch_length_font_size),
            (self.node_size, s.node_size),
            (self.support_decimals, s.support_decimals),
            (self.support_font_size, s.support_font_size),
            (self.label_size, s.label_font_size),
        ):
            _spin(widget, value)
        for widget, value in (
            (self.show_lengths, s.show_branch_lengths),
            (self.show_scale_bar, s.show_scale_bar),
            (self.node_group, s.show_node_markers),
            (self.support_group, s.show_support),
            (self.support_show_names, s.support_show_names),
            (self.support_hide_check,
             getattr(s, "support_hide_below_enabled", False)),
            (self.annot_group, s.show_leaf_labels),
        ):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)
        self.branch_color.blockSignals(True)
        self.branch_color.set_color(s.branch_color)
        self.branch_color.blockSignals(False)
        if s.support_fields is not None:
            chosen = set(s.support_fields)
            for key, cb in self.support_field_checks:
                cb.blockSignals(True)
                cb.setChecked(key in chosen)
                cb.blockSignals(False)
        # Per-metric threshold spin boxes may already exist (loaded tree); keep
        # them in step with the restored thresholds. set_support_fields rebuilds
        # them from the same source when a new tree is opened.
        restored = getattr(s, "support_hide_thresholds", None) or {}
        for key, spin in getattr(self, "support_threshold_spins", []):
            spin.blockSignals(True)
            spin.setValue(float(restored.get(key, 0.0) or 0.0))
            spin.blockSignals(False)
        self._scale_bar_offset = (float(s.scale_bar_offset_x),
                                  float(s.scale_bar_offset_y))
        self._sync_all_sliders()

    def _build(self):
        root = QVBoxLayout(self._content)
        root.setSpacing(8)

        # -- layout ---------------------------------------------------------
        # 1.3: the group is called "布局" and its first row (the layout-mode
        # combo) is labelled "样式"; the rooting buttons moved in here too, so
        # there is no separate "树操作" group any more.
        self.layout_group = self._group("Layout")
        ly = QFormLayout(self.layout_group)
        self.layout_combo = QComboBox()
        for mode in ("Rectangular", "Cladogram", "Radial"):
            self.layout_combo.addItem(self._t(mode), mode.lower())
        idx = self.layout_combo.findData(self.style.layout_mode)
        self.layout_combo.setCurrentIndex(max(idx, 0))
        self.layout_combo.currentIndexChanged.connect(self._on_layout_combo)
        ly.addRow(self._label("Style"), self.layout_combo)
        # horizontal / vertical stretch of the whole tree
        self.h_stretch = QDoubleSpinBox()
        self.h_stretch.setRange(0.2, 5.0)
        self.h_stretch.setSingleStep(0.1)
        self.h_stretch.setValue(self.style.horizontal_stretch)
        ly.addRow(self._label("Horizontal stretch"),
                  self._slider_row(self.h_stretch))
        self.v_stretch = QDoubleSpinBox()
        self.v_stretch.setRange(0.2, 5.0)
        self.v_stretch.setSingleStep(0.1)
        self.v_stretch.setValue(self.style.vertical_stretch)
        ly.addRow(self._label("Vertical stretch"),
                  self._slider_row(self.v_stretch))

        # Branch ordering: sort clades ascending / descending by clade size.
        self.branch_order_combo = QComboBox()
        for mode, key in (("Default", "default"),
                          ("Ascending", "ascending"),
                          ("Descending", "descending")):
            self.branch_order_combo.addItem(self._t(mode), key)
        self.branch_order_combo.setCurrentIndex(
            max(self.branch_order_combo.findData(self.style.branch_order), 0))
        self.branch_order_combo.currentIndexChanged.connect(self._on_branch_order)
        ly.addRow(self._label("Branch order"), self.branch_order_combo)

        # Root length: length of the stem drawn to the left of the root, in
        # the same units as the branch lengths.
        self.root_length = QDoubleSpinBox()
        self.root_length.setRange(0.0, 1000.0)
        self.root_length.setDecimals(4)
        self.root_length.setSingleStep(0.01)
        self.root_length.setValue(self.style.root_length)
        self.root_length.setMaximumWidth(150)
        ly.addRow(self._label("Root length"), self.root_length)

        # -- tree operations (0.01) -----------------------------------------
        # Two aligned rows in ONE grid: 翻转 / 置根 / 中点置根 on top, and
        # 折叠 / 展开 / 全部展开 directly below. Sharing a QGridLayout (with
        # equal column stretches) makes the three columns line up exactly.
        self.sel_hint = QLabel()
        self.sel_hint.setWordWrap(True)
        self.sel_hint.setStyleSheet("color: #888;")
        self._reg(self.sel_hint.setText, "Click a branch or node to select it")
        self.sel_hint.setText(self._t("Click a branch or node to select it"))
        ly.addRow(self.sel_hint)

        self.tree_ops = QWidget(self.layout_group)
        ops_grid = QGridLayout(self.tree_ops)
        ops_grid.setContentsMargins(0, 0, 0, 0)
        ops_grid.setHorizontalSpacing(4)
        ops_grid.setVerticalSpacing(4)
        for col in range(3):
            ops_grid.setColumnStretch(col, 1)

        # "Flip" (formerly "Rotate"): swap the vertical order of a node's
        # child subtrees. The internal callback name stays `on_rotate`.
        self.rotate_btn = self._btn("Flip")
        self.rotate_btn.setEnabled(False)
        self.rotate_btn.clicked.connect(self._on_rotate)
        ops_grid.addWidget(self.rotate_btn, 0, 0)

        # English wording is plain "Root", per the user's request (0.01).
        self.root_branch_btn = self._btn("Root")
        self.root_branch_btn.setEnabled(False)
        self.root_branch_btn.clicked.connect(self._on_root_branch)
        ops_grid.addWidget(self.root_branch_btn, 0, 1)

        self.midpoint_root_btn = self._btn("Midpoint root")
        self.midpoint_root_btn.clicked.connect(self._on_midpoint_root)
        ops_grid.addWidget(self.midpoint_root_btn, 0, 2)

        self.collapse_btn = self._btn("Collapse")
        self.collapse_btn.setEnabled(False)
        self.collapse_btn.clicked.connect(self._on_collapse)
        ops_grid.addWidget(self.collapse_btn, 1, 0)

        self.expand_btn = self._btn("Expand")
        self.expand_btn.setEnabled(False)
        self.expand_btn.clicked.connect(self._on_expand)
        ops_grid.addWidget(self.expand_btn, 1, 1)

        self.expand_all_btn = self._btn("Expand all")
        self.expand_all_btn.clicked.connect(self._on_expand_all)
        ops_grid.addWidget(self.expand_all_btn, 1, 2)

        ly.addRow(self.tree_ops)

        self.collapse_height = QDoubleSpinBox()
        self.collapse_height.setRange(0.0, 500.0)
        self.collapse_height.setDecimals(2)
        self.collapse_height.setSingleStep(0.5)
        self.collapse_height.setValue(self.style.collapse_height)
        ly.addRow(self._label("Collapse height"), self.collapse_height)

        self.collapse_label_edit = QLineEdit()
        self.collapse_label_edit.setEnabled(False)
        self.collapse_label_edit.setPlaceholderText(
            self._t("Label drawn next to a collapsed clade's triangle")
        )
        self.collapse_label_edit.textEdited.connect(self._on_collapse_label)
        ly.addRow(self._label("Collapse label"), self.collapse_label_edit)
        root.addWidget(self.layout_group)

        # -- branch ---------------------------------------------------------
        self.branch_group = self._group("Branch")
        bf = QFormLayout(self.branch_group)
        self.branch_color = ColorButton(self.style.branch_color, self.translator)
        bf.addRow(self._label("Color"), self.branch_color)
        self.branch_width = QDoubleSpinBox()
        self.branch_width.setRange(0.5, 20.0)
        self.branch_width.setSingleStep(0.5)
        self.branch_width.setValue(self.style.branch_width)
        bf.addRow(self._label("Line Width"), self.branch_width)
        self.show_lengths = self._check("Show branch lengths")
        self.show_lengths.setChecked(self.style.show_branch_lengths)
        bf.addRow("", self.show_lengths)
        self.show_scale_bar = self._check("Show scale bar")
        self.show_scale_bar.setChecked(self.style.show_scale_bar)
        bf.addRow("", self.show_scale_bar)
        # -- scale bar (1.9 / 2.1) -----------------------------------------
        # Exact length (0 = automatic). 2.1 dropped the numeric horizontal /
        # vertical offsets and the reset button: position is changed only by
        # dragging the bar on the canvas. The offsets still live in TreeStyle
        # so a drag survives rebuilds, exports and saved settings.
        self.scale_length = QDoubleSpinBox()
        self.scale_length.setRange(0.0, 1000000.0)
        self.scale_length.setDecimals(6)
        self.scale_length.setSingleStep(0.01)
        self.scale_length.setValue(self.style.scale_bar_length)
        self.scale_length.setSpecialValueText(self._t("Auto"))
        self.scale_length.setMaximumWidth(150)
        bf.addRow(self._label("Scale bar length"), self.scale_length)

        self.scale_hint = QLabel()
        self.scale_hint.setWordWrap(True)
        self.scale_hint.setStyleSheet("color: #888;")
        self._reg(self.scale_hint.setText,
                  "Drag the scale bar on the canvas to position it")
        self.scale_hint.setText(self._t(
            "Drag the scale bar on the canvas to position it"))
        bf.addRow(self.scale_hint)

        self.bl_font_size = QDoubleSpinBox()
        self.bl_font_size.setRange(6.0, 48.0)
        self.bl_font_size.setValue(self.style.branch_length_font_size)
        bf.addRow(self._label("Font Size"), self.bl_font_size)
        root.addWidget(self.branch_group)

        # -- nodes ----------------------------------------------------------
        # "Show markers" is now the group box's own checkbox (drawn on the
        # frame line next to the title) — no separate checkbox row.
        self.node_group = self._check_group("Node markers",
                                            self.style.show_node_markers)
        nf = QFormLayout(self.node_group)
        self.node_shape = QComboBox()
        for shape in ("circle", "square", "triangle"):
            self.node_shape.addItem(self._t(shape), shape)
        self.node_shape.setCurrentIndex(self.node_shape.findData(self.style.node_shape))
        nf.addRow(self._label("Shape"), self.node_shape)
        self.node_size = QDoubleSpinBox()
        self.node_size.setRange(2.0, 20.0)
        self.node_size.setValue(self.style.node_size)
        nf.addRow(self._label("Size"), self.node_size)
        root.addWidget(self.node_group)

        # -- support values -------------------------------------------------
        self.support_group = self._check_group("Support Values",
                                               self.style.show_support)
        sf = QFormLayout(self.support_group)
        # 1.8: one checkbox per support metric found in the current tree.
        # Plain trees expose only the original support value, so the whole
        # block stays hidden until there is actually something to choose.
        self.support_fields_label = self._label("Values to display")
        self.support_fields_box = QWidget(self.support_group)
        self.support_fields_layout = QVBoxLayout(self.support_fields_box)
        self.support_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.support_fields_layout.setSpacing(2)
        sf.addRow(self.support_fields_label, self.support_fields_box)
        self.support_show_names = self._check("Show metric names")
        sf.addRow(self.support_show_names)
        # 0.01: hide support values that fall below a per-metric threshold.
        # A master checkbox turns the feature on/off; the per-metric thresholds
        # themselves are built dynamically in set_support_fields (one row per
        # metric found in the current tree).
        self.support_hide_check = self._check("Hide values below threshold")
        self.support_hide_check.toggled.connect(self._on_hide_toggled)
        sf.addRow(self.support_hide_check)
        self.support_thresholds_label = self._label("Per-metric threshold")
        self.support_thresholds_box = QWidget(self.support_group)
        self.support_thresholds_layout = QVBoxLayout(self.support_thresholds_box)
        self.support_thresholds_layout.setContentsMargins(0, 0, 0, 0)
        self.support_thresholds_layout.setSpacing(2)
        sf.addRow(self.support_thresholds_label, self.support_thresholds_box)
        self.support_threshold_spins = []
        self.support_thresholds_label.setVisible(False)
        self.support_thresholds_box.setVisible(False)
        self.support_fields_label.setVisible(False)
        self.support_fields_box.setVisible(False)
        self.support_show_names.setVisible(False)
        self.support_decimals = QSpinBox()
        self.support_decimals.setRange(0, 8)
        self.support_decimals.setValue(self.style.support_decimals)
        sf.addRow(self._label("Decimals"), self.support_decimals)
        self.support_font_size = QDoubleSpinBox()
        self.support_font_size.setRange(6.0, 48.0)
        self.support_font_size.setValue(self.style.support_font_size)
        sf.addRow(self._label("Font Size"), self.support_font_size)
        root.addWidget(self.support_group)

        # -- label annotations (1.5; merged with "Labels" in 2.1) ----------
        # The standalone "Labels" group is gone: its show switch (this group's
        # own title-line checkbox) and its Font Size control now sit at the
        # top of "Label annotations", so every label setting is in one place.
        # Replace the tip labels with rows from a spreadsheet: column A holds
        # the labels as they appear in the tree file (the key), every other
        # column is a candidate label the user can display.
        self.annot_group = self._check_group("Label annotations",
                                             self.style.show_leaf_labels)
        # Compatibility alias: older code and tests refer to the label group
        # by this name; it is the very same widget now.
        self.label_group = self.annot_group
        af = QFormLayout(self.annot_group)
        self.label_size = QDoubleSpinBox()
        self.label_size.setRange(6.0, 48.0)
        self.label_size.setValue(self.style.label_font_size)
        af.addRow(self._label("Font Size"), self.label_size)

        self.annot_file = QLabel(self._t("No table loaded"))
        self.annot_file.setWordWrap(True)
        self.annot_file.setStyleSheet("color: #666;")
        af.addRow(self.annot_file)

        btns = QWidget(self.annot_group)
        btns_l = QHBoxLayout(btns)
        btns_l.setContentsMargins(0, 0, 0, 0)
        btns_l.setSpacing(4)
        self.annot_import_btn = self._btn("Import table...")
        self.annot_import_btn.clicked.connect(self._on_import_table)
        btns_l.addWidget(self.annot_import_btn)
        self.annot_reload_btn = self._btn("Reload table")
        self.annot_reload_btn.setEnabled(False)
        self.annot_reload_btn.clicked.connect(self._on_reload_table)
        btns_l.addWidget(self.annot_reload_btn)
        self.annot_clear_btn = self._btn("Clear table")
        self.annot_clear_btn.setEnabled(False)
        self.annot_clear_btn.clicked.connect(self._on_clear_table)
        btns_l.addWidget(self.annot_clear_btn)
        af.addRow(btns)

        self.annot_sync = self._check("Auto sync")
        self.annot_sync.setChecked(True)
        self.annot_sync.toggled.connect(self._on_auto_sync)
        af.addRow("", self.annot_sync)

        self.annot_header = self._check("First row is header")
        self.annot_header.setChecked(True)
        self.annot_header.toggled.connect(self._on_header_toggled)
        af.addRow("", self.annot_header)

        # 1.6: the sheet's own bold / italic / colour travels to the tips.
        # Size always stays with PhyloClear's "Font Size" control.
        self.annot_style = self._check("Sync table format")
        self.annot_style.setChecked(True)
        self.annot_style.setEnabled(False)
        self.annot_style.toggled.connect(self._on_sync_format_toggled)
        af.addRow("", self.annot_style)

        self.annot_sheet_combo = QComboBox()
        self.annot_sheet_combo.currentIndexChanged.connect(self._on_sheet_changed)
        self.annot_sheet_label = self._label("Sheet")
        af.addRow(self.annot_sheet_label, self.annot_sheet_combo)
        self.annot_sheet_label.setVisible(False)
        self.annot_sheet_combo.setVisible(False)

        self.annot_columns = QListWidget(self.annot_group)
        self.annot_columns.setMaximumHeight(140)
        self.annot_columns.itemChanged.connect(self._on_column_item_changed)
        af.addRow(self.annot_columns)

        self.annot_separator = QLineEdit(" ")
        self.annot_separator.textEdited.connect(self._on_separator_edited)
        af.addRow(self._label("Separator"), self.annot_separator)
        # A space is invisible in a line edit: show its repr so the default
        # (and any whitespace-only separator the user types) is unambiguous.
        self.annot_separator_hint = QLabel("")
        self.annot_separator_hint.setStyleSheet("color: #888;")
        af.addRow("", self.annot_separator_hint)
        self.annot_separator_hint.setText(
            self._t("Current separator: %s") % repr(self.annot_separator.text()))

        self.annot_status = QLabel("")
        self.annot_status.setWordWrap(True)
        self.annot_status.setStyleSheet("color: #666;")
        af.addRow(self.annot_status)
        root.addWidget(self.annot_group)

        # (The "Tree Operations" group was merged into "布局" in 1.3, and the
        # "Selected Node" group was removed in 1.2.)

        root.addStretch(1)

    def _connect_live(self):
        # Style controls: any change refreshes the tree immediately.
        self.branch_color.colorChanged.connect(self._emit_style_change)
        self.branch_width.valueChanged.connect(self._emit_style_change)
        self.show_lengths.toggled.connect(self._emit_style_change)
        self.show_scale_bar.toggled.connect(self._emit_style_change)
        self.scale_length.valueChanged.connect(self._emit_style_change)
        # The three "show" switches are the group boxes themselves.
        self.node_group.toggled.connect(self._emit_style_change)
        self.node_shape.currentIndexChanged.connect(self._emit_style_change)
        self.node_size.valueChanged.connect(self._emit_style_change)
        self.support_group.toggled.connect(self._emit_style_change)
        self.support_show_names.toggled.connect(self._emit_style_change)
        self.support_decimals.valueChanged.connect(self._emit_style_change)
        self.support_font_size.valueChanged.connect(self._emit_style_change)
        self.bl_font_size.valueChanged.connect(self._emit_style_change)
        self.annot_group.toggled.connect(self._emit_style_change)
        self.label_size.valueChanged.connect(self._emit_style_change)
        self.root_length.valueChanged.connect(self._emit_style_change)
        self.collapse_height.valueChanged.connect(self._emit_style_change)
        # Stretch sliders drive their own rebuild (which re-fits the view).
        self.h_stretch.valueChanged.connect(self._on_stretch_changed)
        self.v_stretch.valueChanged.connect(self._on_stretch_changed)

    # -- handlers ----------------------------------------------------------
    def _on_layout_combo(self):
        mode = self.layout_combo.currentData()
        if self.on_layout_change:
            self.on_layout_change(mode)

    def _on_stretch_changed(self, *_):
        self.style.horizontal_stretch = self.h_stretch.value()
        self.style.vertical_stretch = self.v_stretch.value()
        if self.on_stretch:
            self.on_stretch()

    def _on_branch_order(self):
        mode = self.branch_order_combo.currentData()
        if self.on_branch_order:
            self.on_branch_order(mode)

    def _on_root_branch(self):
        if self.selected_node and self.on_root_branch:
            self.on_root_branch(self.selected_node)

    def _on_midpoint_root(self):
        if self.on_midpoint_root:
            self.on_midpoint_root()

    def _on_rotate(self):
        if self.selected_node and self.on_rotate:
            self.on_rotate(self.selected_node)

    def _on_collapse(self):
        if self.selected_node and self.on_collapse:
            self.on_collapse(self.selected_node)

    def _on_expand(self):
        if self.selected_node and self.on_expand:
            self.on_expand(self.selected_node)

    def _on_expand_all(self):
        if self.on_expand_all:
            self.on_expand_all()

    def _on_collapse_label(self, text):
        if self.selected_node and self.on_collapse_label:
            self.on_collapse_label(self.selected_node, text)

    # -- label annotations (1.5) -------------------------------------------
    def _on_import_table(self):
        if self.on_import_table:
            self.on_import_table()

    def _on_reload_table(self):
        if self.on_reload_table:
            self.on_reload_table()

    def _on_clear_table(self):
        if self.on_clear_table:
            self.on_clear_table()

    def _on_auto_sync(self, checked):
        if self.on_auto_sync:
            self.on_auto_sync(bool(checked))

    def _on_header_toggled(self, checked):
        if self._populating or not self.on_has_header:
            return
        self.on_has_header(bool(checked))

    def _on_sync_format_toggled(self, checked):
        if self._populating or not self.on_sync_format:
            return
        self.on_sync_format(bool(checked))

    def _on_sheet_changed(self, *_):
        if self._populating or not self.on_sheet:
            return
        name = self.annot_sheet_combo.currentData()
        if name:
            self.on_sheet(name)

    def _on_column_item_changed(self, _item=None):
        if self._populating or not self.on_columns:
            return
        indices = []
        for i in range(self.annot_columns.count()):
            item = self.annot_columns.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                indices.append(int(item.data(Qt.ItemDataRole.UserRole)))
        self.on_columns(indices)

    def _on_separator_edited(self, text):
        if self._populating or not self.on_separator:
            return
        self.on_separator(text)

    def _emit_style_change(self, *_):
        if self.on_style_change:
            self.on_style_change(self._collect_style())

    def _collect_style(self):
        return {
            "branch_color": self.branch_color.color(),
            "branch_width": self.branch_width.value(),
            "show_branch_lengths": self.show_lengths.isChecked(),
            "show_scale_bar": self.show_scale_bar.isChecked(),
            "scale_bar_length": self.scale_length.value(),
            # 2.1: no numeric offset controls — read back what a canvas drag
            # wrote into the style, otherwise every later style edit would
            # silently reset the dragged position to zero.
            "scale_bar_offset_x": float(
                getattr(self.style, "scale_bar_offset_x", 0.0) or 0.0),
            "scale_bar_offset_y": float(
                getattr(self.style, "scale_bar_offset_y", 0.0) or 0.0),
            "show_node_markers": self.node_group.isChecked(),
            "node_shape": self.node_shape.currentData(),
            "node_size": self.node_size.value(),
            "show_support": self.support_group.isChecked(),
            "support_fields": [key for key, cb in self.support_field_checks
                               if cb.isChecked()],
            "support_show_names": self.support_show_names.isChecked(),
            "support_hide_below_enabled": self.support_hide_check.isChecked(),
            "support_hide_thresholds": {
                key: spin.value() for key, spin in self.support_threshold_spins
            },
            "support_decimals": self.support_decimals.value(),
            "support_font_size": self.support_font_size.value(),
            "branch_length_font_size": self.bl_font_size.value(),
            "show_leaf_labels": self.annot_group.isChecked(),
            "label_font_size": self.label_size.value(),
            "root_length": self.root_length.value(),
            "collapse_height": self.collapse_height.value(),
        }

    # -- public API --------------------------------------------------------
    def set_selected_node(self, node):
        """Remember the selection (used by rooting); no edit fields any more."""
        self.selected_node = node
        self.root_branch_btn.setEnabled(node is not None)
        # Rotation flips the children of a branching node; collapsing needs an
        # internal node too, expanding only makes sense on a collapsed one.
        self.rotate_btn.setEnabled(node is not None and len(node.children) > 1)
        self.collapse_btn.setEnabled(
            node is not None and len(node.children) > 0
            and not getattr(node, "collapsed", False))
        collapsed = bool(node is not None and getattr(node, "collapsed", False))
        self.expand_btn.setEnabled(collapsed)
        self.collapse_label_edit.setEnabled(collapsed)
        collapsed_label = (getattr(node, "collapse_label", None) or "") if node else ""
        self.collapse_label_edit.blockSignals(True)
        self.collapse_label_edit.setText(collapsed_label)
        self.collapse_label_edit.blockSignals(False)
        if node is None:
            self.sel_hint.setText(self._t("Click a branch or node to select it"))
        else:
            self.sel_hint.setText(
                self._t("Selected") + ": " + (node.name or "#%d" % node.index))

    def set_annotations(self, ann, tree=None):
        """Fill the annotation group from a :class:`LabelAnnotations`."""
        self._annotations = ann
        loaded = ann is not None and ann.is_loaded()
        if tree is not None and loaded:
            self._annot_matched, self._annot_total = ann.refresh_match(tree)
        self._populating = True
        try:
            self.annot_reload_btn.setEnabled(loaded)
            self.annot_clear_btn.setEnabled(loaded)
            self.annot_sync.setEnabled(loaded)
            self.annot_header.setEnabled(loaded)
            self.annot_style.setEnabled(loaded)
            self.annot_columns.setEnabled(loaded)
            self.annot_separator.setEnabled(loaded)
            if not loaded:
                self.annot_file.setText(self._t("No table loaded"))
                self.annot_sheet_label.setVisible(False)
                self.annot_sheet_combo.setVisible(False)
                self.annot_sheet_combo.blockSignals(True)
                self.annot_sheet_combo.clear()
                self.annot_sheet_combo.blockSignals(False)
                self.annot_columns.clear()
                self.annot_separator_hint.setText(
                    self._t("Current separator: %s") % repr(
                        ann.separator if ann is not None
                        else self.annot_separator.text()))
                self.set_annotation_status(0, 0, loaded)
                return
            self.annot_file.setText(os.path.basename(ann.path or ""))
            self.annot_header.blockSignals(True)
            self.annot_header.setChecked(ann.has_header)
            self.annot_header.blockSignals(False)
            self.annot_style.blockSignals(True)
            self.annot_style.setChecked(getattr(ann, "sync_format", True))
            self.annot_style.blockSignals(False)
            self.annot_separator.blockSignals(True)
            self.annot_separator.setText(ann.separator)
            self.annot_separator.blockSignals(False)
            self.annot_separator_hint.setText(
                self._t("Current separator: %s") % repr(ann.separator))

            self.annot_sheet_combo.blockSignals(True)
            self.annot_sheet_combo.clear()
            for name in ann.sheets:
                self.annot_sheet_combo.addItem(name, name)
            idx = self.annot_sheet_combo.findData(ann.sheet)
            if idx >= 0:
                self.annot_sheet_combo.setCurrentIndex(idx)
            self.annot_sheet_combo.blockSignals(False)
            multiple = len(ann.sheets) > 1
            self.annot_sheet_label.setVisible(multiple)
            self.annot_sheet_combo.setVisible(multiple)

            self.annot_columns.clear()
            selected = set(ann.selected_columns)
            for index in range(ann.ncols):
                item = QListWidgetItem(ann.columns()[index])
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                              | Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(
                    Qt.CheckState.Checked if index in selected
                    else Qt.CheckState.Unchecked)
                self.annot_columns.addItem(item)
            self.set_annotation_status(ann.matched, ann.tip_count, loaded)
        finally:
            self._populating = False

    def set_annotation_status(self, matched, total, loaded=None):
        """Show how many tip labels the table covers."""
        if loaded is None:
            loaded = self._annotations is not None and self._annotations.is_loaded()
        self._annot_matched, self._annot_total = matched, total
        if not loaded:
            self.annot_status.setText("")
            return
        text = self._t("%d of %d tip labels matched") % (matched, total)
        if total and matched < total:
            # 1.7: make a swallowed first row (or a spelling mismatch)
            # visible instead of leaving the user guessing.
            text += "  ·  " + self._t(
                "%d unmatched - check column A or the header option") % (
                    total - matched)
        self.annot_status.setText(text)

    def set_support_fields(self, fields, selected=None):
        """Rebuild the support-metric checkboxes for the tree just loaded.

        ``fields`` is the ordered [(key, English label)] list from
        ``Tree.support_fields``; ``selected`` is the set of keys to tick.
        A plain tree has a single metric, so the chooser stays hidden.
        """
        fields = list(fields or [])
        self._support_field_specs = fields
        while self.support_fields_layout.count():
            item = self.support_fields_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        while self.support_thresholds_layout.count():
            item = self.support_thresholds_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.support_field_checks = []
        self.support_threshold_spins = []
        chosen = {key for key, _ in fields} if selected is None else set(selected)
        thresholds = getattr(self.style, "support_hide_thresholds", None) or {}
        for key, label in fields:
            cb = QCheckBox(self._t(label), self.support_fields_box)
            cb.blockSignals(True)
            cb.setChecked(key in chosen)
            cb.blockSignals(False)
            cb.toggled.connect(self._emit_style_change)
            self.support_fields_layout.addWidget(cb)
            self.support_field_checks.append((key, cb))
            # per-metric threshold row: metric name + a numeric spin box.
            row = QWidget(self.support_thresholds_box)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(self._label(label))
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 1000.0)
            spin.setDecimals(1)
            spin.setSingleStep(1.0)
            spin.setValue(float(thresholds.get(key, 0.0) or 0.0))
            spin.valueChanged.connect(self._on_threshold_changed)
            # Threshold spins are created dynamically (after the build-time
            # wheel-filter loop), so install the wheel guard here too: a wheel
            # over the spin must scroll the panel, never nudge the value.
            spin.installEventFilter(self._no_wheel_filter)
            rl.addWidget(spin)
            rl.addStretch(1)
            self.support_thresholds_layout.addWidget(row)
            self.support_threshold_spins.append((key, spin))
        multi = len(fields) > 1
        self.support_fields_label.setVisible(multi)
        self.support_fields_box.setVisible(multi)
        self.support_show_names.setVisible(multi)
        has_metrics = len(fields) >= 1
        self.support_thresholds_label.setVisible(has_metrics)
        self.support_thresholds_box.setVisible(has_metrics)
        self._update_threshold_enabled()

    def _on_hide_toggled(self, checked):
        """Enable/disable the per-metric thresholds and push the change."""
        self._update_threshold_enabled()
        self._emit_style_change()

    def _on_threshold_changed(self):
        """Any threshold edit is collected live by _collect_style()."""
        self._emit_style_change()

    def _update_threshold_enabled(self):
        """Threshold boxes are only editable while the feature is on."""
        enabled = getattr(self, "support_hide_check", None)
        active = bool(enabled.isChecked()) if enabled is not None else False
        for _, spin in getattr(self, "support_threshold_spins", []):
            spin.setEnabled(active)

    def set_layout_mode(self, mode):
        """Sync the combo to ``mode`` without triggering a rebuild."""
        idx = self.layout_combo.findData(mode)
        if idx >= 0:
            self.layout_combo.blockSignals(True)
            self.layout_combo.setCurrentIndex(idx)
            self.layout_combo.blockSignals(False)

    def set_scale_bar_position(self, dx, dy):
        """Remember the offset produced by dragging the scale bar (2.1).

        The numeric offset controls were removed in 2.1, but the renderer
        still writes the offset into ``TreeStyle`` on every drag; keeping it
        here too makes it easy to persist with the saved settings. No rebuild
        happens in this callback (that would destroy the item being dragged).
        """
        self._scale_bar_offset = (float(dx), float(dy))

    def retranslate(self):
        """Rebuild all text after a language switch."""
        for setter, source_key in self._translatable:
            setter(self._t(source_key))
        # Dynamic support-metric checkboxes are not in _translatable (their
        # widgets are destroyed on every tree change), so refresh them here.
        labels = dict(self._support_field_specs)
        for key, cb in self.support_field_checks:
            if key in labels:
                cb.setText(self._t(labels[key]))
        # 0.01: the per-metric threshold rows are also dynamic; refresh their
        # metric-name labels so a language switch stays consistent.
        for key, spin in self.support_threshold_spins:
            row = spin.parent()
            if row is not None:
                for child in row.children():
                    if isinstance(child, QLabel) and key in labels:
                        child.setText(self._t(labels[key]))
                        break
        # scale bar (1.9): the "Auto" special value and tooltips are not in
        # the ordinary text registry, so refresh them explicitly.
        self.scale_length.setSpecialValueText(self._t("Auto"))
        self.annot_separator_hint.setText(
            self._t("Current separator: %s") % repr(self.annot_separator.text()))
        for i in range(self.layout_combo.count()):
            mode = self.layout_combo.itemData(i)
            self.layout_combo.setItemText(i, self._t(mode.capitalize()))
        for i in range(self.node_shape.count()):
            shape = self.node_shape.itemData(i)
            self.node_shape.setItemText(i, self._t(shape))
        for i in range(self.branch_order_combo.count()):
            label = {"default": "Default", "ascending": "Ascending",
                     "descending": "Descending"}[
                self.branch_order_combo.itemData(i)]
            self.branch_order_combo.setItemText(i, self._t(label))
        self.branch_color.set_translator(self.translator)
        placeholder = self._t("Label drawn next to a collapsed clade's triangle")
        self.collapse_label_edit.setPlaceholderText(placeholder)
        # label annotations (1.5): button/checkbox/label texts come from the
        # translation registry; only tooltips and the dynamic status line need
        # a manual refresh.
        loaded = self._annotations is not None and self._annotations.is_loaded()
        if not loaded:
            self.annot_file.setText(self._t("No table loaded"))
        self.set_annotation_status(self._annot_matched, self._annot_total,
            loaded)
        if self.selected_node is None:
            self.sel_hint.setText(self._t("Click a branch or node to select it"))
        else:
            self.sel_hint.setText(
                self._t("Selected") + ": " + (self.selected_node.name
                or "#%d" % self.selected_node.index))
