#!/usr/bin/env python3
"""PhyloClear entry point.

An interactive phylogenetic tree viewer and editor.
Run with:  python main.py [tree_file]
"""

import os
import sys
import traceback

# Ensure the project root is on sys.path when run as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox

from phyloview import __app_name__, __version__
from phyloview import settings as settings_mod
from phyloview.app_icon import app_icon
from phyloview.i18n import Translator
from phyloview.ui import MainWindow


def _log_dir():
    # Write the crash log next to the executable/source so it is easy to find.
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return base


def _excepthook(exc_type, exc_value, exc_tb):
    """Log any uncaught exception instead of silently exiting."""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(os.path.join(_log_dir(), "phyloview_error.log"), "a",
                  encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:  # noqa: BLE001
        pass
    try:
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None, "PhyloClear",
                "An unexpected error occurred:\n\n%s\n\n"
                "Details were written to phyloview_error.log" % exc_value,
            )
    except Exception:  # noqa: BLE001
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())

    # Default language is Chinese.
    translator = Translator()

    # 0.01: no global auto-restore. A settings file is opened explicitly
    # (File -> Open / Load settings / drag & drop / command line) and resumes
    # the tree it belongs to together with all of its settings.
    window = MainWindow(translator, persist=True)
    window.show()

    # optional: a tree OR a settings file passed on the command line
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        arg = sys.argv[1]
        if settings_mod.is_project_path(arg):
            window.load_project(arg)
        else:
            window.load_file(arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
