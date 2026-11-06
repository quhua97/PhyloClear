"""Per-tree "settings files" (PhyloClear projects), version 0.01.

A settings file is **bound to one tree**.  It is plain UTF-8 JSON and stores:

* the tree file it belongs to (absolute path *plus* a path relative to the
  settings file, so a project can be moved together with its tree);
* the complete :class:`~phyloview.rendering.style.TreeStyle` (layout, stretch,
  colours, fonts, support metrics, scale-bar length and its dragged offset);
* interface language and window geometry;
* the label-annotation configuration (table path, sheet, header flag, selected
  columns, separator, format sync and auto sync).

Opening such a file reopens that tree and restores every setting, so tree A and
tree B can each have their own file and be picked up later exactly where they
were left.  Exit also writes the current state back into the *open* project
file (never into a global profile), which keeps "continue editing" seamless.

Applying a file is done in :meth:`MainWindow.apply_settings`, since it needs to
talk to widgets; this module only handles the data and the file I/O.
"""

import json
import os
import sys

from . import __app_name__, __version__

__all__ = [
    "SettingsError", "FORMAT_VERSION", "PROJECT_EXT", "PROJECT_EXTS",
    "collect", "save_settings", "load_settings", "validate",
    "is_project_path", "normalise_path", "resolve_tree_path",
    "default_settings_path", "suggested_path",
]

FORMAT_VERSION = 2
PROJECT_EXT = ".phcproj"
# .json is accepted when *loading* so files written by 2.1 still open.
PROJECT_EXTS = (PROJECT_EXT, ".json")


class SettingsError(ValueError):
    """The settings file is missing, unreadable or not a PhyloClear file."""


def is_project_path(path):
    """True for a settings/project file (as opposed to a tree or a table)."""
    return os.path.splitext(str(path))[1].lower() in PROJECT_EXTS


def normalise_path(path):
    """Append ``.phcproj`` unless the user typed a known extension."""
    if os.path.splitext(path)[1].lower() in PROJECT_EXTS:
        return path
    return path + PROJECT_EXT


def collect(window, project_path=None):
    """Snapshot the current state of ``window`` as a JSON-safe dictionary.

    ``project_path`` (when saving) lets us also store the tree path relative to
    the settings file, which survives moving both files to another folder.
    """
    # Once a window has a project open, collect() is deterministic even when
    # called without an explicit path (e.g. by the exit handler / tests).
    project_path = project_path or getattr(window, "project_path", None)
    ann = window.annotations
    panel = window.panel
    geom = window.geometry()
    style = {}
    for key, value in window.style.to_dict().items():
        if isinstance(value, (str, int, float, bool, type(None),
                              list, tuple, dict)):
            style[key] = value
    tree_path = getattr(window, "tree_path", None)
    tree = getattr(window, "current_tree", None)
    data = {
        "format": FORMAT_VERSION,
        "kind": "%s settings" % __app_name__,
        "app": __app_name__,
        "app_version": __version__,
        "language": window.translator.language,
        "style": style,
        "geometry": [geom.x(), geom.y(), geom.width(), geom.height()],
        "tree_path": tree_path,
        "tree_name": getattr(tree, "name", None),
        "annotations": {
            "path": ann.path,
            "sheet": ann.sheet,
            "has_header": bool(ann.has_header),
            "header_auto": bool(getattr(ann, "_header_auto", False)),
            "selected_columns": list(ann.selected_columns),
            "separator": ann.separator,
            "sync_format": bool(ann.sync_format),
            "auto_sync": bool(panel.annot_sync.isChecked()),
        },
    }
    if project_path and tree_path:
        try:
            data["tree_path_relative"] = os.path.relpath(
                os.path.abspath(tree_path),
                os.path.dirname(os.path.abspath(project_path)))
        except (OSError, ValueError):  # different drives etc.
            pass
    return data


def resolve_tree_path(data, base_dir=None):
    """Find the tree a settings file refers to (relative path wins on move)."""
    path = data.get("tree_path")
    if isinstance(path, str) and os.path.isfile(path):
        return path
    rel = data.get("tree_path_relative")
    if isinstance(rel, str) and base_dir:
        candidate = os.path.normpath(os.path.join(base_dir, rel))
        if os.path.isfile(candidate):
            return candidate
    return path if isinstance(path, str) else None


def save_settings(path, data):
    """Atomically write ``data`` to ``path``."""
    if not isinstance(data, dict):
        raise SettingsError("settings data must be a dictionary")
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def load_settings(path):
    """Read a settings file; raise :class:`SettingsError` on bad content."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SettingsError(str(exc)) from exc
    if not isinstance(data, dict):
        raise SettingsError("settings file is not a JSON object")
    return data


def validate(data):
    """Guard against opening an arbitrary JSON file as a project."""
    if not isinstance(data, dict):
        raise SettingsError("settings file is not a JSON object")
    if data.get("app") != __app_name__ or not isinstance(data.get("style"), dict):
        raise SettingsError("Settings file is not a PhyloClear project")
    return data


def default_settings_path():
    """Legacy per-user path (2.1 auto-save). Kept for compatibility only.

    0.01 does **not** auto-save or auto-restore a global snapshot: settings
    belong to an explicitly saved, per-tree project file.
    """
    override = os.environ.get("PHYLOCLEAR_SETTINGS_PATH")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, __app_name__, "settings.json")


def suggested_path(tree_path=None):
    """Default filename offered by the "Save settings..." dialog.

    Named after the tree so "tree 1" and "tree 2" naturally get two different
    settings files sitting next to their trees.
    """
    if tree_path:
        folder = os.path.dirname(os.path.abspath(tree_path))
        stem = os.path.splitext(os.path.basename(tree_path))[0]
        return os.path.join(folder, stem + PROJECT_EXT)
    try:
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
    except Exception:  # pragma: no cover - defensive
        base = os.getcwd()
    return os.path.join(base, "%s_settings%s" % (__app_name__, PROJECT_EXT))
