"""Main application window: menus, toolbar, canvas and style dock."""

import os

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, QPointF, QRectF
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QApplication,
    QFileDialog,
    QMessageBox,
    QDockWidget,
    QComboBox,
    QToolBar,
)  # noqa: F401  (QApplication used by _adjust_panel_width)

from .. import __app_name__, __version__
from .. import settings as settings_mod
from ..app_icon import app_icon
from ..tree.detect import load_tree_file
from ..rendering import TreeStyle, TreeRenderer, export_scene
from ..annotations import LabelAnnotations
from ..label_export import export_labels, normalise_path, LabelExportError
from ..tables import TableError, is_table_file
from .tree_canvas import TreeCanvas
from .style_panel import StylePanel


# 2.0: windows opened by dropping an additional tree file. Keeping them in a
# module-level list stops CPython from collecting (and closing) them as soon
# as the drop handler returns.
_EXTRA_WINDOWS = []


def open_tree_in_new_window(path, translator, origin=None):
    """Load ``path`` in a NEW top-level window; never touch ``origin``."""
    window = MainWindow(translator)
    if not window.load_file(path):
        window.deleteLater()
        return None
    if origin is not None:
        # Cascade the new window a little so both are visible.
        window.move(origin.x() + 40, origin.y() + 40)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _EXTRA_WINDOWS.append(window)
    window.show()
    return window


class MainWindow(QMainWindow):
    def __init__(self, translator, persist=False):
        super().__init__()
        self.translator = translator
        # 2.1: only the primary window owns the automatic save/restore; extra
        # windows opened by dropping another tree must not overwrite it.
        self._persist = bool(persist)
        # 0.01: settings live in a per-tree project file, not a global
        # profile. These two fields remember which project this window is
        # editing so closing it can write the latest state back to that file.
        self.project_path = None
        self._project_tree_path = None
        self.tree_path = None
        self.style = TreeStyle()
        self.renderer = TreeRenderer()
        self.trees = []
        self.current_tree = None
        # 1.5: tip labels can be replaced by rows from a spreadsheet. The same
        # object is handed to the renderer (it asks for each label) and to the
        # panel (it edits the selection).
        self.annotations = LabelAnnotations(self)
        self.renderer.annotations = self.annotations
        # Keep the labels in sync with the file on disk: Qt's watcher catches
        # plain "Save" while the slower timer also covers editors that write to
        # a temporary file and move it over the original.
        self._table_watcher = QFileSystemWatcher(self)
        self._table_watcher.fileChanged.connect(self._on_table_file_changed)
        self._table_signature = None
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(500)
        self._sync_timer.timeout.connect(self._reload_table_from_disk)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)
        self._poll_timer.timeout.connect(self._poll_table)
        # Files may also be dropped onto the window as a whole (not only the
        # canvas), which is what users expect when dragging from Explorer.
        self.setAcceptDrops(True)

        self._tr = translator.tr

        self.canvas = TreeCanvas(self.renderer)
        self.setCentralWidget(self.canvas)

        self.panel = StylePanel(self.style, translator)
        # 1.3: no title on the right-hand dock — the panel speaks for itself.
        self.dock = QDockWidget("", self)
        self.dock.setWidget(self.panel)
        self.dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        # wiring
        self.canvas.nodeSelected.connect(self._on_node_selected)
        self.canvas.fileDropped.connect(self._handle_dropped_path)
        self.panel.on_style_change = self._on_style_change
        self.panel.on_layout_change = self._on_layout_change
        self.panel.on_stretch = self._on_stretch
        self.panel.on_branch_order = self._on_branch_order
        self.panel.on_root_branch = self._on_root_branch
        self.panel.on_midpoint_root = self._on_midpoint_root
        self.panel.on_rotate = self._on_rotate
        self.panel.on_collapse = self._on_collapse
        self.panel.on_expand = self._on_expand
        self.panel.on_expand_all = self._on_expand_all
        self.panel.on_collapse_label = self._on_collapse_label
        # label annotations (1.5) — tip labels taken from a spreadsheet
        self.panel.on_import_table = self._import_table_dialog
        self.panel.on_reload_table = self._reload_table
        self.panel.on_clear_table = self._clear_table
        self.panel.on_auto_sync = self._set_auto_sync
        self.panel.on_has_header = self._set_has_header
        self.panel.on_sheet = self._set_table_sheet
        self.panel.on_columns = self._set_label_columns
        self.panel.on_separator = self._set_label_separator
        # label formatting (1.6) — copy the sheet's emphasis onto the labels
        self.panel.on_sync_format = self._set_sync_format
        self.annotations.labelsChanged.connect(self._on_labels_changed)
        self.translator.languageChanged.connect(self._on_language_changed)
        # 1.9: dragging the scale bar updates the style and the panel's
        # numeric offsets without rebuilding the scene mid-drag.
        self.renderer.on_scale_bar_moved = self._on_scale_bar_moved
        self.canvas.on_item_drag_finished = self._on_scale_bar_drag_finished

        # Debounce style changes so rapid control tweaks coalesce into one
        # rebuild instead of hammering the scene (avoids lag on large trees).
        self._pending_style = None
        self._style_timer = QTimer(self)
        self._style_timer.setSingleShot(True)
        self._style_timer.setInterval(80)
        self._style_timer.timeout.connect(self._apply_pending_style)

        self._build_menus()
        # The language switcher is a persistent toolbar: build it exactly once
        # here (NOT inside _build_menus, which runs again on every language
        # switch and would otherwise stack a duplicate toolbar with a stale
        # highlight). _build_menus only (re)builds the File/Help menus.
        self._build_language_toolbar()
        self.resize(1280, 820)
        # 0.01: a minimal phylogenetic-tree icon, also used for the .exe.
        self.setWindowIcon(app_icon())
        self._update_title()
        self._show_hint(self._tr("Drop a tree file or a label table here"))

    # -- UI construction ---------------------------------------------------
    def _build_menus(self):
        t = self._tr
        mb = self.menuBar()
        mb.clear()

        # File
        m_file = mb.addMenu(t("File"))
        self.act_open = QAction(t("Import tree file..."), self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._open_dialog)
        m_file.addAction(self.act_open)
        # 1.5: relabel tips from a spreadsheet. Keyboard shortcuts use the
        # standard key sequence objects where they exist.
        self.act_import_labels = QAction(t("Import label annotations..."), self)
        self.act_import_labels.triggered.connect(self._import_table_dialog)
        m_file.addAction(self.act_import_labels)

        # 2.1: all settings (style, language, annotations, open tree) can be
        # written to a JSON file and loaded back later.
        m_file.addSeparator()
        self.act_save_settings = QAction(t("Save settings..."), self)
        self.act_save_settings.triggered.connect(self._save_settings_dialog)
        m_file.addAction(self.act_save_settings)
        self.act_load_settings = QAction(t("Load settings..."), self)
        self.act_load_settings.triggered.connect(self._load_settings_dialog)
        m_file.addAction(self.act_load_settings)

        # 0.04: the Export submenu was moved below "Load settings".
        m_file.addSeparator()
        m_export = m_file.addMenu(t("Export"))
        self.act_export_png = QAction(t("Export as PNG..."), self)
        self.act_export_png.triggered.connect(lambda: self._export_dialog("png"))
        m_export.addAction(self.act_export_png)
        self.act_export_jpg = QAction(t("Export as JPEG..."), self)
        self.act_export_jpg.triggered.connect(lambda: self._export_dialog("jpg"))
        m_export.addAction(self.act_export_jpg)
        self.act_export_svg = QAction(t("Export as SVG..."), self)
        self.act_export_svg.triggered.connect(lambda: self._export_dialog("svg"))
        m_export.addAction(self.act_export_svg)
        self.act_export_pdf = QAction(t("Export as PDF..."), self)
        self.act_export_pdf.triggered.connect(lambda: self._export_dialog("pdf"))
        m_export.addAction(self.act_export_pdf)
        m_export.addSeparator()
        self.act_export_newick = QAction(t("Export as Newick..."), self)
        self.act_export_newick.triggered.connect(self._export_newick)
        m_export.addAction(self.act_export_newick)
        m_export.addSeparator()
        # 1.9: the tip labels themselves can be written out as a list/table.
        # The format is chosen explicitly in the save dialog (txt/csv/xlsx).
        self.act_export_labels = QAction(t("Export labels..."), self)
        self.act_export_labels.triggered.connect(self._export_labels)
        m_export.addAction(self.act_export_labels)

        # Help
        m_help = mb.addMenu(t("Help"))
        self.act_about = QAction(t("About"), self)
        self.act_about.triggered.connect(self._show_about)
        m_help.addAction(self.act_about)

    # -- actions -----------------------------------------------------------
    def _open_dialog(self):
        t = self._tr
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("Open Tree or Settings"),
            "",
            t("Tree files (*.nwk *.tre *.newick *.nex *.nexus *.nxs *.phy);;"
              "Settings files (*.phcproj *.json);;All files (*.*)"),
        )
        if not path:
            return
        if settings_mod.is_project_path(path):
            # 0.01: opening a settings file resumes the tree it belongs to.
            self.load_project(path)
        else:
            self.load_file(path)

    def _export_dialog(self, ext):
        if self.current_tree is None:
            QMessageBox.warning(self, self._tr("Error"), self._tr("No tree loaded"))
            return
        t = self._tr
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Export Tree"),
            "",
            t("Image files (*.png *.jpg);;SVG files (*.svg);;PDF files (*.pdf)"),
        )
        if not path:
            return
        try:
            export_scene(self.renderer.scene, path)
            self.statusBar().showMessage("OK: " + path, 5000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, t("Export failed:"), str(exc))

    def _export_newick(self):
        if self.current_tree is None:
            QMessageBox.warning(self, self._tr("Error"), self._tr("No tree loaded"))
            return
        t = self._tr
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Export as Newick..."),
            "",
            t("Newick files (*.nwk *.tre *.newick);;All files (*.*)"),
        )
        if not path:
            return
        label_map = {}
        if self.annotations.is_loaded():
            # Write the labels that are drawn on screen (a tip whose row has no
            # value for the selected columns keeps its original name).
            for leaf in self.current_tree.leaves:
                text = self.annotations.label_for(leaf.name)
                if text:
                    label_map[leaf.name] = text
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.current_tree.to_newick(label_map or None))
            self.statusBar().showMessage("OK: " + path, 5000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, t("Export failed:"), str(exc))

    def _label_rows(self):
        """(label in the tree file, label drawn on screen) for every tip."""
        if self.current_tree is None:
            return []
        rows = []
        for leaf in self.current_tree.leaves:
            original = leaf.name or ""
            displayed = self.renderer.display_name(leaf) or original
            rows.append((original, displayed))
        return rows

    def _export_labels(self):
        """Write the tip labels in the format the user picks in the dialog."""
        if self.current_tree is None:
            QMessageBox.warning(self, self._tr("Error"), self._tr("No tree loaded"))
            return
        t = self._tr
        filters = t("Text files (*.txt);;CSV files (*.csv);;"
                    "Excel workbooks (*.xlsx)")
        path, selected = QFileDialog.getSaveFileName(
            self, t("Export Labels"), "", filters)
        if not path:
            return
        path, fmt = normalise_path(path, selected)
        headers = (t("Original label"), t("Displayed label"))
        rows = self._label_rows()
        try:
            export_labels(path, rows, fmt=fmt, headers=headers)
            self.statusBar().showMessage(
                "%s: %s  |  %d %s" % (
                    t("Labels exported"), path, len(rows), t("tips")), 8000)
        except (LabelExportError, OSError) as exc:
            QMessageBox.critical(self, t("Export failed:"), str(exc))

    # -- settings files / projects (0.01) ----------------------------------
    def _save_settings(self, path):
        """Write a settings file bound to the tree currently open."""
        t = self._tr
        path = settings_mod.normalise_path(path)
        try:
            data = settings_mod.collect(self, project_path=path)
            settings_mod.save_settings(path, data)
        except (OSError, ValueError) as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, t("Error"),
                "%s\n%s" % (t("Failed to save settings:"), exc))
            return False
        self.project_path = path
        self._project_tree_path = self.tree_path
        self.statusBar().showMessage(
            "%s: %s" % (t("Project saved"), path), 8000)
        self._update_title()
        return True

    def _save_settings_dialog(self):
        t = self._tr
        path, _ = QFileDialog.getSaveFileName(
            self, t("Save Settings"),
            settings_mod.suggested_path(self.tree_path),
            t("Settings files (*.phcproj *.json);;All files (*.*)"))
        if not path:
            return False
        return self._save_settings(path)

    def _load_settings_dialog(self):
        t = self._tr
        path, _ = QFileDialog.getOpenFileName(
            self, t("Load Settings"), "",
            t("Settings files (*.phcproj *.json);;All files (*.*)"))
        if not path:
            return False
        return self.load_project(path)

    def load_project(self, path):
        """Open a settings file: restore its tree AND every visual setting.

        This is the 0.01 meaning of "save settings": tree 1 gets one file,
        tree 2 gets another, and opening either resumes that exact tree.
        """
        t = self._tr
        try:
            data = settings_mod.validate(settings_mod.load_settings(path))
            ok = self.apply_settings(
                data, base_dir=os.path.dirname(os.path.abspath(path)))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            QMessageBox.critical(
                self, t("Error"),
                "%s\n%s" % (t("Failed to load settings:"), exc))
            return False
        if ok:
            self.project_path = path
            self._project_tree_path = self.tree_path
            self.statusBar().showMessage(
                "%s: %s" % (t("Project loaded"), path), 8000)
            self._update_title()
        return ok

    def apply_settings(self, data, base_dir=None):
        """Restore a snapshot produced by :func:`settings.collect`.

        ``base_dir`` is the folder holding the settings file: the tree path is
        stored both absolute and relative, so a moved project still finds its
        tree. Order matters: the tree must be open before the label table
        (header auto-detection compares the first row against real tips), and
        the style is applied last because loading a tree resets the default
        support metrics.
        """
        if not isinstance(data, dict):
            return False
        t = self._tr
        language = data.get("language")
        if language in ("en", "zh_CN"):
            self.translator.set_language(language)

        tree_path = settings_mod.resolve_tree_path(data, base_dir)
        if isinstance(tree_path, str) and tree_path and os.path.isfile(tree_path):
            self.load_file(tree_path)
        elif isinstance(tree_path, str) and tree_path:
            self.statusBar().showMessage(
                "%s %s" % (t("Tree file not found:"), tree_path), 8000)

        ann_data = data.get("annotations") or {}
        table_path = ann_data.get("path") if isinstance(ann_data, dict) else None
        if isinstance(table_path, str) and os.path.isfile(table_path):
            self.load_table(table_path)
            ann = self.annotations
            sheet = ann_data.get("sheet")
            if (isinstance(sheet, str) and sheet != ann.sheet
                    and sheet in ann.sheets):
                ann.set_sheet(sheet, tree=self.current_tree)
            if "has_header" in ann_data:
                ann.set_has_header(bool(ann_data["has_header"]),
                                   tree=self.current_tree)
            if "header_auto" in ann_data:
                ann._header_auto = bool(ann_data["header_auto"])
            if "selected_columns" in ann_data:
                ann.set_columns(list(ann_data["selected_columns"]),
                                tree=self.current_tree)
            if "separator" in ann_data:
                ann.set_separator(str(ann_data["separator"]),
                                  tree=self.current_tree)
            ann.set_sync_format(bool(ann_data.get("sync_format", True)))
            sync = self.panel.annot_sync
            sync.blockSignals(True)
            sync.setChecked(bool(ann_data.get("auto_sync", True)))
            sync.blockSignals(False)
            if sync.isChecked():
                self._install_table_watch()
            self.panel.set_annotations(ann, tree=self.current_tree)

        style_data = data.get("style") or {}
        if isinstance(style_data, dict):
            known = {k: v for k, v in style_data.items()
                     if isinstance(k, str) and hasattr(self.style, k)}
            self.style.update(**known)
        self.panel.sync_from_style()
        fields = (getattr(self.current_tree, "support_fields", []) or []
                  if self.current_tree is not None else [])
        self.panel.set_support_fields(fields, self.style.support_fields)
        # Branch ordering is a tree operation, not just a style flag.
        if (self.current_tree is not None
                and self.style.branch_order != "default"):
            self._on_branch_order(self.style.branch_order)

        geom = data.get("geometry")
        if isinstance(geom, (list, tuple)) and len(geom) == 4:
            try:
                self.setGeometry(*[int(v) for v in geom])
            except (TypeError, ValueError):
                pass
        if self.current_tree is not None:
            self._rebuild(fit=False)
        self._update_title()
        return True

    # 2.1's global auto-save / auto-restore is deliberately NOT used by 0.01:
    # a settings file belongs to exactly one tree. These two helpers remain
    # only so old files and external tools can still be read.
    def save_last_settings(self):
        """Legacy: write the per-user snapshot (unused by the app)."""
        try:
            settings_mod.save_settings(
                settings_mod.default_settings_path(), settings_mod.collect(self))
            return True
        except (OSError, ValueError):
            return False

    def restore_last_settings(self):
        """Legacy: read the per-user snapshot (unused by the app)."""
        path = settings_mod.default_settings_path()
        if not os.path.isfile(path):
            return False
        try:
            return self.apply_settings(settings_mod.load_settings(path))
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def _on_scale_bar_moved(self, dx, dy):
        """Mirror a scale-bar drag into the style and the panel.

        Deliberately cheap: this runs on every mouse-move of a drag, so the
        expensive bounding-box / pan-room refresh is deferred to mouse-up.
        """
        self.panel.set_scale_bar_position(dx, dy)

    def _on_scale_bar_drag_finished(self):
        """Once per drag: make the moved bar part of the fit/pan extent."""
        rect = self.renderer.scene.itemsBoundingRect()
        if rect.isValid():
            self.renderer.content_rect = rect.adjusted(-24.0, -24.0, 24.0, 24.0)
        self.canvas.ensure_pan_room()
        self.statusBar().showMessage(
            "%s: %g, %g px" % (self._tr("Scale bar position"),
                               self.style.scale_bar_offset_x,
                               self.style.scale_bar_offset_y), 3000)

    # -- drag & drop -------------------------------------------------------
    # Anything dropped anywhere on the window is accepted: trees open as usual,
    # spreadsheets reload/import the tip labels.
    def dragEnterEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData() else []
        paths = [u.toLocalFile() for u in urls if u.toLocalFile()]
        if paths:
            for path in paths:
                self._handle_dropped_path(path)
            event.acceptProposedAction()
            return
        event.ignore()

    def _handle_dropped_path(self, path):
        if settings_mod.is_project_path(path):
            # 0.01: dropping a settings file resumes its tree + settings.
            self.load_project(path)
        elif is_table_file(path):
            self.load_table(path)
        elif self.current_tree is not None:
            # 2.0: dropping a tree while one is already open used to replace
            # it. Keep the current tree and open the new file in a new window.
            open_tree_in_new_window(path, self.translator, self)
        else:
            self.load_file(path)

    # -- label annotations (1.5) -------------------------------------------
    # The tip labels can be replaced by rows of a spreadsheet whose first
    # column holds the labels as they appear in the tree file.
    def _import_table_dialog(self):
        t = self._tr
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("Import Label Table"),
            "",
            t("Spreadsheet files (*.xlsx *.xlsm *.csv *.tsv *.txt);;"
              "All files (*.*)"),
        )
        if path:
            self.load_table(path)

    def load_table(self, path):
        """Import (or re-import) an annotation table from ``path``."""
        try:
            self.annotations.load(path, tree=self.current_tree)
        except (TableError, OSError, ValueError) as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, self._tr("Error"),
                "%s\n%s" % (self._tr("Failed to load table:"), exc))
            return
        # ``labelsChanged`` has already refreshed the panel and redrawn the
        # tree; all that is left is the watch for external edits.
        self._install_table_watch()
        self.statusBar().showMessage(
            "%s  |  %s" % (self._tr("Labels updated from %s") % path,
                           self._match_text()), 8000)

    def _reload_table(self):
        """Manual "Reload table" button."""
        try:
            self.annotations.reload(tree=self.current_tree)
        except (TableError, OSError, ValueError) as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, self._tr("Error"),
                "%s\n%s" % (self._tr("Failed to load table:"), exc))
            return
        self._table_signature = self._table_signature_of()
        self.statusBar().showMessage(
            "%s  |  %s" % (
                self._tr("Labels updated from %s") % self.annotations.path,
                self._match_text()), 5000)

    def _clear_table(self):
        """Forget the table: tips show the labels read from the tree file."""
        watched = self._table_watcher.files()
        if watched:
            self._table_watcher.removePaths(watched)
        self._poll_timer.stop()
        self._sync_timer.stop()
        self._table_signature = None
        self.annotations.clear()
        self.statusBar().showMessage(self._tr("Label table cleared"), 4000)

    def _set_auto_sync(self, enabled):
        if enabled:
            self._install_table_watch()
        else:
            watched = self._table_watcher.files()
            if watched:
                self._table_watcher.removePaths(watched)
            self._poll_timer.stop()
            self._sync_timer.stop()

    def _set_has_header(self, flag):
        try:
            self.annotations.set_has_header(bool(flag), tree=self.current_tree)
        except (TableError, OSError, ValueError) as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, self._tr("Error"),
                "%s\n%s" % (self._tr("Failed to load table:"), exc))

    def _set_table_sheet(self, name):
        try:
            self.annotations.set_sheet(name, tree=self.current_tree)
        except (TableError, OSError, ValueError) as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, self._tr("Error"),
                "%s\n%s" % (self._tr("Failed to load table:"), exc))

    def _set_label_columns(self, indices):
        self.annotations.set_columns(indices, tree=self.current_tree)

    def _set_label_separator(self, text):
        self.annotations.set_separator(text, tree=self.current_tree)

    def _set_sync_format(self, enabled):
        """Copy the spreadsheet's bold / italic / colour onto the labels."""
        self.annotations.set_sync_format(bool(enabled))
        self.statusBar().showMessage(
            self._tr("Table formatting applied") if enabled
            else self._tr("Table formatting ignored"), 4000)

    def _on_labels_changed(self):
        """Redraw after any change of the label table."""
        if self.current_tree is not None and self.annotations.is_loaded():
            self.annotations.refresh_match(self.current_tree)
        self.panel.set_annotations(self.annotations)
        self._rebuild(fit=False)

    def _match_text(self):
        return self._tr("%d of %d tip labels matched") % (
            self.annotations.matched, self.annotations.tip_count)

    # -- watching the file on disk ----------------------------------------
    def _table_signature_of(self):
        path = self.annotations.path
        if not path or not os.path.isfile(path):
            return None
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _install_table_watch(self):
        """Watch the table file so external edits refresh the labels."""
        path = self.annotations.path
        if not path:
            return
        self._table_signature = self._table_signature_of()
        if not self.panel.annot_sync.isChecked():
            return
        watched = [p for p in self._table_watcher.files() if p != path]
        if watched:
            self._table_watcher.removePaths(watched)
        try:
            self._table_watcher.addPath(path)
        except Exception:  # noqa: BLE001 - watcher quota, ignore
            pass
        # The polling timer is the safety net: some editors (Excel included)
        # write a temporary file and move it over the original, which Qt's
        # watcher can miss entirely.
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _on_table_file_changed(self, path):
        if self.annotations.path and path != self.annotations.path:
            return
        # Debounce: writers touch the file several times per save.
        self._sync_timer.start()

    def _poll_table(self):
        if not self.annotations.path or not self.panel.annot_sync.isChecked():
            self._poll_timer.stop()
            return
        signature = self._table_signature_of()
        if signature is None or signature == self._table_signature:
            return
        self._reload_table_from_disk()

    def _reload_table_from_disk(self):
        """Re-read the table and keep going if it is still being written."""
        signature = self._table_signature_of()
        if signature is None:
            # File missing for the moment (rename-based save); the poller will
            # notice once it reappears.
            return
        try:
            self.annotations.reload(tree=self.current_tree)
        except Exception:  # noqa: BLE001 - transient read error while saving
            return
        self._table_signature = signature
        self._install_table_watch()
        self.statusBar().showMessage(
            "%s  |  %s" % (
                self._tr("Labels updated from %s") % self.annotations.path,
                self._match_text()), 5000)

    def _set_layout(self, mode):
        self.style.layout_mode = mode
        self.panel.set_layout_mode(mode)
        self._rebuild()

    def _build_language_toolbar(self):
        tb = QToolBar(self._tr("Language"), self)
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)
        self.lang_zh = QAction("中文", self)
        self.lang_zh.setCheckable(True)
        self.lang_zh.triggered.connect(
            lambda: self.translator.set_language("zh_CN")
        )
        tb.addAction(self.lang_zh)
        self.lang_en = QAction("English", self)
        self.lang_en.setCheckable(True)
        self.lang_en.triggered.connect(
            lambda: self.translator.set_language("en")
        )
        tb.addAction(self.lang_en)
        self._sync_language_checks()

    def _sync_language_checks(self):
        self.lang_en.setChecked(self.translator.language == "en")
        self.lang_zh.setChecked(self.translator.language == "zh_CN")

    def _show_about(self):
        t = self._tr
        box = QMessageBox(self)
        box.setWindowTitle(t("About PhyloClear"))
        # 0.01: show the same minimal tree icon used by the window / exe.
        box.setIconPixmap(self.windowIcon().pixmap(64, 64))
        # 0.01: 关于内容改为 软件名+版本 / 名称全称展开 / 中文副标题。
        # 全称展开中 Phylo 与 C L E A R 各自加粗并增大字号（即 PhyloClear 的由来）。
        expansion = (
            "<b><span style='font-size:1.3em'>Phylo</span></b>genetic tree "
            "<b><span style='font-size:1.3em'>C</span></b>ustomization, "
            "<b><span style='font-size:1.3em'>L</span></b>ayout, "
            "<b><span style='font-size:1.3em'>E</span></b>diting, "
            "<b><span style='font-size:1.3em'>A</span></b>nnotation &amp; "
            "<b><span style='font-size:1.3em'>R</span></b>endering"
        )
        box.setText(
            "<h2>%s %s</h2>"
            "<p>%s</p>"
            % (
                __app_name__,
                __version__,
                expansion,
            )
        )
        box.exec()

    # -- core logic --------------------------------------------------------
    def load_file(self, path):
        """Load a tree file into THIS window; return True on success (2.0)."""
        try:
            trees = load_tree_file(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self._tr("Error"),
                                 "%s\n%s" % (self._tr("Failed to load tree:"), exc))
            return False
        if not trees:
            QMessageBox.warning(self, self._tr("Error"),
                                self._tr("Failed to load tree:") + " (empty)")
            return False
        # A project file is bound to its tree. Loading a *different* tree
        # detaches it, so closing the window cannot overwrite that project
        # with settings that belong to another tree.
        if self.project_path and self._project_tree_path:
            if (os.path.normcase(os.path.abspath(path))
                    != os.path.normcase(os.path.abspath(self._project_tree_path))):
                self.project_path = None
                self._project_tree_path = None
        self.trees = trees
        self.tree_path = path
        self._set_current_tree(0)
        self._show_hint("")
        extra = ""
        if len(getattr(self.current_tree, "support_fields", []) or []) > 1:
            # 1.8: tell the user where to select QP-IC / LQ-IC / EQP-IC or
            # the two halves of an IQ-TREE "100/100" label.
            extra = "  |  " + self._tr(
                "Multiple support metrics detected — choose them in Support Values")
        self.statusBar().showMessage(
            "%s  |  %d taxa%s" % (path, self.current_tree.n_taxa, extra), 8000
        )
        # A table imported before the tree now has labels to match against.
        if self.annotations.is_loaded():
            self.annotations.maybe_recheck_header(self.current_tree)
            self.annotations.refresh_match(self.current_tree)
            self.panel.set_annotations(self.annotations)
            self._rebuild(fit=True)
        self._update_title()
        return True

    @staticmethod
    def _default_support_fields(fields):
        """Which metrics are shown when a tree with several of them is opened.

        QuartetScores (original + three IC scores) starts on the original
        support value, matching what the file itself used to show; IQ-TREE
        starts with both halves of "100/100", also matching the file.
        """
        keys = [key for key, _ in fields]
        if any(key in keys for key in ("qp-ic", "lq-ic", "eqp-ic")):
            return ["original"] if "original" in keys else keys[:1]
        return keys

    def _set_current_tree(self, idx):
        self.current_tree = self.trees[idx]
        # Remember the child order as read from the file so that "Default"
        # branch ordering can restore it after a sort.
        self.current_tree.snapshot_order()
        # 1.8: the available support metrics belong to this specific tree.
        fields = getattr(self.current_tree, "support_fields", []) or []
        self.style.support_fields = self._default_support_fields(fields)
        self.style.support_show_names = False
        self.panel.set_support_fields(fields, self.style.support_fields)
        self.panel.support_show_names.blockSignals(True)
        self.panel.support_show_names.setChecked(False)
        self.panel.support_show_names.blockSignals(False)
        # 1.7: the label table may have been imported while a different tree
        # was open. Rejudge "first row is a header" against THIS tree's tips
        # so a real data row is never swallowed just because of load order.
        if self.annotations.is_loaded():
            self.annotations.maybe_recheck_header(self.current_tree)
        self._rebuild()

    def _rebuild(self, fit=True):
        if self.current_tree is None:
            return
        if fit:
            # Loading / re-rooting / sorting genuinely changes the topology:
            # fitting the whole tree is what the user expects there.
            self.renderer.rebuild(self.current_tree, self.style)
            self.canvas.fit_to_window()
            return
        # 2.0: a style-only rebuild (stretch, collapse height, font size,
        # colours, ...) must NOT move the tree on screen. renderer.rebuild()
        # clears the scene and resets sceneRect to the tight content box; Qt
        # then clamps the scroll bars and the drawing jumps to the top-left.
        # Save the view state and restore it afterwards.
        canvas = self.canvas
        h_bar = canvas.horizontalScrollBar()
        v_bar = canvas.verticalScrollBar()
        want_h, want_v = h_bar.value(), v_bar.value()
        old_rect = self.renderer.scene.sceneRect()
        self.renderer.rebuild(self.current_tree, self.style)
        scene = self.renderer.scene
        content = self.renderer.content_rect
        if old_rect.isValid():
            # Scroll-bar values are measured from the top-left of sceneRect,
            # so keep that origin fixed. Only grow to the right/bottom when
            # the new drawing is larger; the old panning margin stays intact.
            left, top = old_rect.left(), old_rect.top()
            right = max(old_rect.right(), content.right())
            bottom = max(old_rect.bottom(), content.bottom())
            scene.setSceneRect(QRectF(QPointF(left, top), QPointF(right, bottom)))
        else:
            scene.setSceneRect(content)
        h_bar.setValue(want_h)
        v_bar.setValue(want_v)

    def _on_node_selected(self, node):
        self.panel.set_selected_node(node)

    def _on_style_change(self, updates):
        self._pending_style = updates
        self._style_timer.start()

    def _apply_pending_style(self):
        if self._pending_style is None:
            return
        updates = dict(self._pending_style)
        # 2.1: the scale-bar offset is written by dragging on the canvas, not
        # by a panel control. A queued (80 ms debounce) style snapshot may
        # predate the drag, so never let it undo the dragged position.
        updates["scale_bar_offset_x"] = self.style.scale_bar_offset_x
        updates["scale_bar_offset_y"] = self.style.scale_bar_offset_y
        self.style.update(**updates)
        self._pending_style = None
        self._rebuild(fit=False)

    def _on_layout_change(self, mode):
        self._set_layout(mode)

    def _reselect_node(self, node):
        branch = self.renderer.node_to_branch.get(node)
        if branch is not None:
            branch.setSelected(True)
        triangle = self.renderer.node_to_collapse.get(node)
        if triangle is not None:
            triangle.setSelected(True)

    # -- tree operations ---------------------------------------------------
    def _on_stretch(self):
        # Horizontal/vertical stretch changes the tree's proportions. We keep
        # the current zoom/pan so the effect is actually visible: horizontal
        # stretch lengthens the horizontal branch segments (and the scale bar
        # grows with them), vertical stretch lengthens the vertical connectors.
        self._rebuild(fit=False)

    def _on_branch_order(self, mode):
        """Branch ordering — sort clades by clade size (number of tips)."""
        if self.current_tree is None:
            return
        self.style.branch_order = mode
        if mode == "ascending":
            self.current_tree.order_clades(descending=False)
        elif mode == "descending":
            self.current_tree.order_clades(descending=True)
        else:
            self.current_tree.restore_order()
        # Re-index so the leaf list (and therefore the y coordinates) follows
        # the new traversal order.
        self.current_tree.index_nodes()
        self._rebuild(fit=True)

    def _on_root_branch(self, node):
        if self.current_tree is None:
            return
        if node is None or node.parent is None:
            self.statusBar().showMessage(self._tr("Select a branch/node first"), 4000)
            return
        try:
            # Root ON THE BRANCH above the selected clade (standard "rooting
            # along a branch", as in FigTree / phytools): a new root is created
            # on that edge. The selected clade stays monophyletic (its members
            # remain one clade) and the new root is bifurcating / resolved.
            #
            # Rooting *at the node itself* would instead make that node the root
            # with three children (its two original children plus the whole
            # former up-side), i.e. a basal polytomy that breaks the clade apart
            # — which is exactly the bug that used to split Russula/Tricholoma.
            self.current_tree.reroot(node, frac=0.5)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self._tr("Error"), str(exc))
            return
        self._rebuild(fit=True)
        # The selected node is now a child of the new root and keeps its own
        # branch (so it is drawn with a horizontal segment) — re-highlight it.
        self.panel.set_selected_node(node)
        self._reselect_node(node)

    def _on_midpoint_root(self):
        if self.current_tree is None:
            return
        try:
            self.current_tree.midpoint_root()
            self.current_tree.index_nodes()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, self._tr("Error"), str(exc))
            return
        self._rebuild(fit=True)

    # -- rotation / collapse (1.4) ----------------------------------------
    def _on_rotate(self, node):
        """Rotation — flip the selected node / its child subtrees."""
        if self.current_tree is None:
            return
        if node is None or len(node.children) < 2:
            self.statusBar().showMessage(
                self._tr("Select a branching node first"), 4000)
            return
        # Flipping only swaps the order of the node's immediate children (each
        # of which is an entire subtree), so topology, clade membership and
        # branch lengths are untouched.
        self.current_tree.rotate(node)
        self.current_tree.index_nodes()
        self._rebuild(fit=False)
        self.panel.set_selected_node(node)
        self._reselect_node(node)

    def _on_collapse(self, node):
        """Collapse the selected clade into a triangle."""
        if self.current_tree is None:
            return
        if node is None or len(node.children) == 0:
            self.statusBar().showMessage(
                self._tr("Select a branching node first"), 4000)
            return
        label = node.collapse_label
        if label is None:
            label = node.name or ""
        self.current_tree.set_collapsed(node, True, label=label)
        self._rebuild(fit=True)
        self.panel.set_selected_node(node)
        self._reselect_node(node)

    def _on_expand(self, node):
        """Expand the selected collapsed clade again."""
        if self.current_tree is None or node is None:
            return
        if not node.collapsed:
            return
        self.current_tree.set_collapsed(node, False)
        self._rebuild(fit=True)
        self.panel.set_selected_node(node)
        self._reselect_node(node)

    def _on_expand_all(self):
        if self.current_tree is None:
            return
        if self.current_tree.expand_all():
            if self.panel.selected_node is not None:
                self.panel.set_selected_node(self.panel.selected_node)
            self._rebuild(fit=True)

    def _on_collapse_label(self, node, text):
        """Rename the label printed next to a collapsed clade's triangle."""
        if self.current_tree is None or node is None:
            return
        if self.current_tree.set_collapse_label(node, text):
            self._rebuild(fit=False)

    # -- language / title --------------------------------------------------
    def _on_language_changed(self, language):
        self._build_menus()
        self.panel.retranslate()
        self._adjust_panel_width()
        self.dock.setWindowTitle("")
        self._update_title()
        self._sync_language_checks()
        # 2.0: the empty-canvas hint was translated only once at start-up,
        # so switching to English left the Chinese text on screen.
        if self.current_tree is None:
            self._show_hint(self._tr("Drop a tree file or a label table here"))

    def _adjust_panel_width(self):
        """Resize the right dock so every translated label fits without
        horizontal scrolling.

        Chinese text is noticeably wider than the same English string, so after
        a language switch the panel can clip its labels. We measure the inner
        content widget's preferred width and force the dock widget's minimum
        width to it.

        Note: ``QMainWindow.resizeDocks`` is a no-op on some Qt builds (and
        under the offscreen platform), so we drive the width through the
        widget's minimum size instead — the dock then grows to fit and the user
        can still drag it wider, just never narrow enough to clip the text.
        """
        content = getattr(self.panel, "_content", None)
        if content is None:
            return
        w = content.sizeHint().width()
        if w <= 0:
            return
        # leave a little room for the vertical scrollbar gutter / frame
        w += 22
        # generous cap so pathological content can never swallow the canvas
        w = min(w, 760)
        self.panel.setMinimumWidth(w)
        # The new minimum only takes effect once the layout is recomputed, so
        # pump the event loop to grow the dock immediately (also needed by the
        # test harness, which reads the width synchronously).
        QApplication.processEvents()

    def _update_title(self):
        name = self.current_tree.name if self.current_tree else None
        title = "%s %s" % (__app_name__, __version__)
        if name:
            title += " - " + name
        if self.project_path:
            title += " - [%s]" % os.path.basename(self.project_path)
        self.setWindowTitle(title)

    def _show_hint(self, text):
        self.canvas.show_empty_hint(text)

    def closeEvent(self, event):
        # 0.01: write the latest settings back into the OPEN project file,
        # but only while it is still bound to the same tree. There is no
        # global snapshot that could mix up "tree 1" and "tree 2".
        current = (os.path.normcase(os.path.abspath(self.tree_path))
                   if self.tree_path else None)
        saved = (os.path.normcase(os.path.abspath(self._project_tree_path))
                 if self._project_tree_path else None)
        # Equal (including both None) means the window still edits the tree
        # this project was saved for.
        if self.project_path and current == saved:
            try:
                settings_mod.save_settings(
                    self.project_path,
                    settings_mod.collect(self,
                                         project_path=self.project_path))
            except (OSError, ValueError):
                pass
        # 2.0: drop the strong reference while the QObject is still alive
        # (a destroyed() lambda would already point at a deleted C++ object).
        if self in _EXTRA_WINDOWS:
            _EXTRA_WINDOWS.remove(self)
        super().closeEvent(event)
