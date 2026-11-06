"""Label annotations: replace tree tip labels with rows from a spreadsheet.

An annotation table is a sheet whose **first column** holds the labels as they
appear in the tree file (the "key" column). Every other column holds an
alternative label — Chinese names, voucher numbers, host, country, ... The user
picks which of those columns should be drawn on the tree; the values of the
selected columns are joined with a separator and replace the tip label.

Because the table is re-read from disk whenever the file changes, the same file
can stay open in Excel/WPS: saving it updates the labels in PhyloClear.

Formatting
----------
Since 1.6 the **bold / italic / colour** typed into the sheet travels to the
tree as well, including Excel's rich text (``Genus`` roman + ``species``
italic). The font *size* of the sheet is never used — that stays with
PhyloClear's own "Font Size" control, so one table can serve figures of very
different sizes.
"""

from PySide6.QtCore import QObject, Signal

from .tables import read_table, TableError, TableData, CellRun

# The column that is matched against the tip labels in the tree.
KEY_COLUMN = 0


def normalize_key(value):
    """Normalise a table key / tip label for matching."""
    text = "" if value is None else str(value)
    return text.strip().strip("'\"")


def _squash(value):
    """Even looser key: lower-case, no spaces/underscores."""
    return normalize_key(value).replace("_", "").replace(" ", "").lower()


def _trim_runs(runs, target):  # noqa: ARG001 - target documents the intent
    """Remove the whitespace ``str.strip()`` took off, one run at a time."""
    items = [CellRun(run.text, run.bold, run.italic, run.color)
             for run in runs]
    while items and items[0].text != items[0].text.lstrip():
        items[0].text = items[0].text.lstrip()
        if not items[0].text:
            items.pop(0)
    while items and items[-1].text != items[-1].text.rstrip():
        items[-1].text = items[-1].text.rstrip()
        if not items[-1].text:
            items.pop()
    return items or None


class LabelAnnotations(QObject):
    """Maps tree tip labels to labels taken from a spreadsheet."""

    tableChanged = Signal()     # a table was loaded / cleared
    labelsChanged = Signal()    # column selection or separator changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.data = None            # :class:`TableData`
        self.has_header = True
        # 1.8: a single space is the default join between selected columns
        # (the user asked for this explicitly). It is kept across table
        # reloads; only the field in the panel changes it.
        self.separator = " "
        self.selected_columns = []  # column indices, in drawing order
        # Draw the emphasis (bold / italic / colour) found in the sheet.
        self.sync_format = True
        self.matched = 0
        self.tip_count = 0
        # True while the "first row = header?" question is still automatic.
        # It stays True across tree switches and auto-sync reloads; only an
        # explicit click on the panel's checkbox turns it off (1.7).
        self._header_auto = False
        self._exact = {}
        self._folded = {}
        self._squashed = {}
        # key -> row index, the same three tiers as above but usable to reach
        # the parallel cell-format table.
        self._exact_pos = {}
        self._folded_pos = {}
        self._squashed_pos = {}

    # -- state -------------------------------------------------------------
    def is_loaded(self):
        return self.data is not None

    @property
    def sheet(self):
        return self.data.sheet if self.data else None

    @property
    def sheets(self):
        return list(self.data.sheets) if self.data else []

    @property
    def ncols(self):
        return self.data.ncols if self.data else 0

    def columns(self):
        """Display names of every column, in table order."""
        if self.data is None:
            return None
        return [self.data.column_name(i) for i in range(self.data.ncols)]

    def has_any_formatting(self):
        """True when the sheet carries emphasis PhyloClear would draw."""
        if self.data is None or self.data.formats is None:
            return False
        for line in self.data.formats:
            for runs in line:
                if runs and any(run.formatted for run in runs):
                    return True
        return False

    def clear(self):
        """Forget the table; tips fall back to their original labels."""
        self.path = None
        self.data = None
        self.selected_columns = []
        self._exact = self._folded = self._squashed = {}
        self._exact_pos = self._folded_pos = self._squashed_pos = {}
        self.matched = self.tip_count = 0
        self.tableChanged.emit()
        self.labelsChanged.emit()

    # -- loading -----------------------------------------------------------
    def load(self, path, tree=None, sheet=None, has_header=None,
             keep_selection=False):
        """Read ``path`` and index it by its key column.

        ``has_header=None`` auto-detects: if the first row's key cell already
        matches one of the tree's tip labels the row is treated as data, not as
        a header (this is the usual layout of a hand-made label table). With no
        tree yet the first row is kept as data, and the guess is repeated for
        every tree that is opened until the user sets the option by hand.
        """
        same_file = self.path == path
        previous = list(self.selected_columns) if same_file else []
        self.path = path
        # Detect the first row ourselves so the *raw* row can be inspected
        # (reading with has_header=True already discards it).
        data = read_table(path, sheet=sheet, has_header=False)
        if has_header is None:
            self._header_auto = True
            self.has_header = self._guess_has_header(data, tree)
            # 1.7: do NOT lock the answer here. The tree that happens to be
            # open at import time is not necessarily the tree the user will
            # annotate (they may open/switch trees later), and an answer
            # guessed with no tree at all is only a placeholder. Only an
            # explicit click on "First row is a header" locks it.
        else:
            self.has_header = bool(has_header)
            self._header_auto = False
        if self.has_header and data.rows:
            data.headers = list(data.rows.pop(0))
            # The parallel format table must lose the same row, or every tip
            # would look one row off when its emphasis is fetched.
            if data.formats:
                data.formats.pop(0)
        data.has_header = self.has_header

        keep_selection = bool(keep_selection)
        self.data = data
        self._index_rows()

        ncols = data.ncols
        if keep_selection and previous:
            kept = [i for i in previous if i < ncols]
        else:
            # Show something useful straight away: the first non-key column.
            kept = [1 if ncols > 1 else 0] if ncols else []
        self.selected_columns = [i for i in kept if i < ncols]
        self.refresh_match(tree)
        self.tableChanged.emit()
        self.labelsChanged.emit()
        return self

    def _header_argument(self):
        """``None`` keeps auto-detection alive; a bool is an explicit choice."""
        return None if self._header_auto else self.has_header

    def reload(self, tree=None):
        """Re-read the file from disk (keeps column selection and options).

        1.7: an auto-sync reload (or the "Refresh table" button) must not
        freeze a placeholder answer that was guessed before a tree was open.
        """
        if self.path is None:
            return
        self.load(self.path, tree=tree, sheet=self.sheet,
                  has_header=self._header_argument(), keep_selection=True)

    def set_sheet(self, name, tree=None):
        """Switch to another worksheet of the same workbook."""
        if self.path is None or name == self.sheet:
            return
        self.load(self.path, tree=tree, sheet=name,
                  has_header=self._header_argument(), keep_selection=True)

    def set_has_header(self, flag, tree=None):
        """Re-read treating the first row as a header (or as data)."""
        if self.path is None or bool(flag) == self.has_header:
            return
        self.load(self.path, tree=tree, sheet=self.sheet,
                  has_header=bool(flag), keep_selection=True)

    def maybe_recheck_header(self, tree):
        """Re-settle the first-row question for the *current* tree.

        A table imported while a different tree (or no tree at all) was open
        may have been judged with the wrong set of tip labels. 1.7 calls this
        on every tree change, and keeps the auto-decision alive until the user
        explicitly toggles "First row is a header". Returns True when re-read.
        """
        if not self._header_auto or self.path is None:
            return False
        if tree is None or not getattr(tree, "leaves", None):
            return False
        try:
            data = read_table(self.path, sheet=self.sheet, has_header=False)
        except (TableError, OSError, ValueError):
            # A save in progress can leave the file unreadable for a moment;
            # the next poll / tree change will ask again.
            return False
        guess = self._guess_has_header(data, tree)
        if guess == self.has_header:
            return False
        # Pass None so load() re-guesses against this tree and stays automatic.
        self.load(self.path, tree=tree, sheet=self.sheet,
                  has_header=None, keep_selection=True)
        return True

    @staticmethod
    def _guess_has_header(data, tree):
        """True when row 1 looks like column titles rather than data."""
        if not data.rows or not data.rows[0]:
            return True
        first_key = normalize_key(data.rows[0][KEY_COLUMN])
        if not first_key:
            return True
        names = [normalize_key(n.name)
                 for n in (tree.leaves if tree else [])]
        names = [name for name in names if name]
        if not names:
            # 1.7: with nothing to compare against, never gamble on throwing
            # away a real data row. maybe_recheck_header() settles the
            # question as soon as a tree is available.
            return False
        # Same three tiers as row_for(): a slightly different spelling still
        # means "this row is a tip, not a column title".
        exact = set(names)
        folded = {name.casefold() for name in names}
        squashed = {_squash(name) for name in names}
        is_tip = (first_key in exact
                  or first_key.casefold() in folded
                  or _squash(first_key) in squashed)
        return not is_tip

    def _index_rows(self):
        self._exact = {}
        self._folded = {}
        self._squashed = {}
        self._exact_pos = {}
        self._folded_pos = {}
        self._squashed_pos = {}
        if self.data is None:
            return
        for position, row in enumerate(self.data.rows):
            key = normalize_key(row[KEY_COLUMN]) if row else ""
            if not key:
                continue
            self._exact.setdefault(key, row)
            self._folded.setdefault(key.casefold(), row)
            self._squashed.setdefault(_squash(key), row)
            self._exact_pos.setdefault(key, position)
            self._folded_pos.setdefault(key.casefold(), position)
            self._squashed_pos.setdefault(_squash(key), position)

    # -- selection ---------------------------------------------------------
    def set_columns(self, indices, tree=None):
        """Choose which columns are drawn, preserving the given order."""
        clean = []
        for i in indices:
            i = int(i)
            if 0 <= i < self.ncols and i not in clean:
                clean.append(i)
        if clean == self.selected_columns:
            return False
        self.selected_columns = clean
        self.refresh_match(tree)
        self.labelsChanged.emit()
        return True

    def set_separator(self, text, tree=None):
        if text == self.separator:
            return False
        self.separator = text
        self.labelsChanged.emit()
        return True

    def set_sync_format(self, flag):
        """Copy the sheet's bold / italic / colour onto the tip labels."""
        flag = bool(flag)
        if flag == self.sync_format:
            return False
        self.sync_format = flag
        self.labelsChanged.emit()
        return True

    # -- lookup ------------------------------------------------------------
    def row_for(self, name):
        key = normalize_key(name)
        row = self._exact.get(key)
        if row is None:
            row = self._folded.get(key.casefold())
        if row is None:
            row = self._squashed.get(_squash(key))
        return row

    def row_index_for(self, name):
        """Position of the matching row, needed to reach its cell formats."""
        key = normalize_key(name)
        for table, probe in ((self._exact_pos, key),
                             (self._folded_pos, key.casefold()),
                             (self._squashed_pos, _squash(key))):
            position = table.get(probe)
            if position is not None:
                return position
        return None

    def label_for(self, name):
        """Display label for a tip, or ``None`` to keep the original."""
        if self.data is None:
            return None
        row = self.row_for(name)
        if row is None:
            return None
        parts = []
        for i in self.selected_columns:
            value = row[i] if i < len(row) else ""
            value = "" if value is None else str(value).strip()
            if value:
                parts.append(value)
        if not parts:
            return None
        return self.separator.join(parts)

    # Same label again, but as pieces each carrying their own character
    # format — the sheet's emphasis survives into the drawing.
    def runs_for(self, name):
        """``[(text, format)]`` for one tip, or ``None``.

        ``format`` is a ``{"bold", "italic", "color"}`` dict, or ``None`` for a
        piece drawn with PhyloClear's own label style (the separators, and any
        cell the sheet left unformatted). The concatenation of all ``text``
        values always equals :meth:`label_for`, so switching the emphasis off
        changes nothing except the emphasis.
        """
        if self.data is None or self.data.formats is None:
            return None
        if not self.sync_format:
            return None
        position = self.row_index_for(name)
        if position is None:
            return None
        row = self.data.rows[position]
        pieces = []
        for index in self.selected_columns:
            raw = row[index] if index < len(row) else ""
            value = "" if raw is None else str(raw).strip()
            if not value:
                continue
            if pieces:
                # Separator text always wears the software's own style.
                if self.separator:
                    pieces.append((self.separator, None))
            runs = self._runs_at(position, index, value)
            if runs is None:
                pieces.append((value, None))
            else:
                pieces.extend((run.text, run.as_dict()) for run in runs)
        pieces = [(text, fmt) for text, fmt in pieces if text]
        return pieces or None

    def _runs_at(self, position, index, value):
        """Cell runs trimmed to match the already-stripped ``value``."""
        runs = self.data.runs_at(position, index)
        if not runs:
            return None
        joined = "".join(run.text for run in runs)
        if joined == value:
            return runs
        if joined.strip() != value:
            # The cell text was altered beyond trimming — carrying the
            # emphasis over would highlight the wrong characters.
            return None
        return _trim_runs(runs, value)

    def refresh_match(self, tree=None):
        """Count how many tips the table actually covers."""
        if tree is None:
            return (self.matched, self.tip_count)
        leaves = tree.leaves
        self.tip_count = len(leaves)
        self.matched = sum(1 for leaf in leaves
                           if self.row_for(leaf.name) is not None)
        return (self.matched, self.tip_count)

    def __repr__(self):  # pragma: no cover - debugging aid
        if self.data is None:
            return "<LabelAnnotations none>"
        return "<LabelAnnotations %s sheet=%r cols=%s>" % (
            self.path, self.sheet, self.selected_columns)
