"""Reading label tables (spreadsheets) with the standard library only.

Supported formats
-----------------
``.xlsx`` / ``.xlsm``
    Office Open XML workbooks (Excel and WPS both write these). The file is a
    zip archive, so we read its parts with :mod:`zipfile` and parse the sheet
    XML directly — no third-party package needed and nothing extra to bundle
    into the executable.
``.csv`` / ``.tsv`` / ``.txt``
    Delimited text, encoding auto-detected (UTF-8 BOM, UTF-8, GBK, cp1252).

Old *binary* formats (``.xls``, WPS ``.et``, ``.xlsb``) are compound documents
and are deliberately not implemented: asking the user to re-save the sheet as
``.xlsx`` once is far friendlier than shipping a guessed BIFF parser.

Cell formatting
---------------
Since 1.6 the **bold / italic / colour** of each cell is read alongside its
text, so a tip label can inherit the emphasis the user gave it in Excel or
WPS. Formatting is recorded per *run* — a cell may be bold as a whole (a font
in ``styles.xml``) or only in part (rich-text ``<r><rPr>`` runs inside a shared
string).

The **font size of the spreadsheet is always ignored**: how big a tip label
looks is decided by PhyloClear's own "Font Size" control.
"""

import csv
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

# Extensions we can read.
READABLE_EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".tsv", ".txt")
# Known office formats we cannot read (kept so drag-and-drop can explain
# itself instead of trying to parse the file as a tree).
UNREADABLE_EXTENSIONS = (".xls", ".xlsb", ".et", ".ett", ".ods", ".numbers",
                         ".dif", ".prn", ".sylk", ".slk")


class TableError(Exception):
    """Raised when a table cannot be read."""


def is_table_file(path):
    """True for any file that should be routed to the label-table importer."""
    ext = os.path.splitext(path or "")[1].lower()
    return ext in READABLE_EXTENSIONS or ext in UNREADABLE_EXTENSIONS


def is_readable_table(path):
    ext = os.path.splitext(path or "")[1].lower()
    return ext in READABLE_EXTENSIONS


def _localname(tag):
    """Strip the XML namespace from a tag (``{uri}name`` -> ``name``)."""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def _text(node):
    """Concatenated text of a cell/run node (handles rich-text ``<r><t>``)."""
    parts = []
    for child in node.iter():
        if _localname(child.tag) == "t":
            parts.append(child.text or "")
    return "".join(parts)


class CellRun:
    """A piece of a cell's text together with its own character format.

    Only what a phylogenetic figure can use is kept: bold, italic and colour.
    Runs are enough for Excel's rich text (``"Genus "`` normal + ``"species"``
    italic) — the classic way binomials are written.

    Deliberately absent: font size, underline, strike-through and font family.
    Those either belong to PhyloClear's own styling (size, family) or do not
    belong on a tip label at all.
    """

    __slots__ = ("text", "bold", "italic", "color")

    def __init__(self, text, bold=False, italic=False, color=None):
        self.text = text
        self.bold = bool(bold)
        self.italic = bool(italic)
        self.color = color or None

    @property
    def formatted(self):
        """True when the run carries anything PhyloClear would draw."""
        return bool(self.bold or self.italic or self.color)

    def as_dict(self):
        return {"bold": self.bold, "italic": self.italic,
                "color": self.color}

    def __eq__(self, other):  # pragma: no cover - test convenience
        return (isinstance(other, CellRun) and self.text == other.text
                and self.bold == other.bold and self.italic == other.italic
                and self.color == other.color)

    def __repr__(self):  # pragma: no cover - debugging aid
        tags = "".join([
            "b" if self.bold else "", "i" if self.italic else "",
            " %s" % self.color if self.color else ""])
        return "<CellRun %r%s>" % (self.text, " " + tags if tags.strip() else "")


class TableData:
    """The parsed contents of one sheet: a header row plus data rows.

    ``rows`` always holds the *data* rows; when the file has a header row it is
    kept separately in ``headers``. Column counts are normalised: short rows are
    padded with empty strings and trailing empty rows are dropped.

    ``formats`` mirrors ``rows`` cell for cell: each entry is either ``None``
    (no formatting worth applying — draw with PhyloClear's own label style) or a
    list of :class:`CellRun` covering exactly that cell's text. Delimited files
    carry no formatting, so ``formats`` stays ``None`` for them.
    """

    def __init__(self, path, sheet=None, sheets=(), headers=(), rows=(),
                 has_header=True, formats=None):
        self.path = path
        self.sheet = sheet
        self.sheets = list(sheets)
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.has_header = has_header
        self.formats = formats

    def runs_at(self, row, col):
        """Formatted runs of one cell, or ``None`` when there are none."""
        if self.formats is None:
            return None
        if not (0 <= row < len(self.formats)):
            return None
        line = self.formats[row]
        return line[col] if 0 <= col < len(line) else None

    @property
    def ncols(self):
        width = len(self.headers)
        for row in self.rows:
            width = max(width, len(row))
        return width

    @property
    def nrows(self):
        return len(self.rows)

    def column_name(self, index):
        if 0 <= index < len(self.headers) and self.headers[index]:
            return str(self.headers[index])
        return _column_letter(index)

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<TableData %s sheet=%r rows=%d cols=%d>" % (
            os.path.basename(self.path or "-"), self.sheet,
            self.nrows, self.ncols)


def _column_letter(index):
    """0 -> A, 1 -> B, 25 -> Z, 26 -> AA (used when a sheet has no header)."""
    letters = ""
    index = max(index, 0)
    while True:
        letters = chr(ord("A") + index % 26) + letters
        index = index // 26 - 1
        if index < 0:
            return letters


def _col_index(ref):
    """Column index from a cell reference such as ``C7`` (2)."""
    idx = 0
    for ch in ref:
        if ch.isalpha():
            idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
        else:
            break
    return max(idx - 1, 0)


def read_table(path, sheet=None, has_header=True):
    """Read a spreadsheet into a :class:`TableData`.

    Raises :class:`TableError` with a human-readable reason when the format is
    unsupported or the archive is damaged.
    """
    if not path or not os.path.isfile(path):
        raise TableError("file not found: %s" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext in UNREADABLE_EXTENSIONS:
        raise TableError(
            "unsupported table format '%s' — please save the sheet as "
            ".xlsx, .csv or .tsv" % ext)
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path, sheet=sheet, has_header=has_header)
    if ext in (".csv", ".tsv", ".txt"):
        return _read_text(path, has_header=has_header)
    raise TableError("unsupported table format '%s'" % (ext or "-"))


# -- cell formatting (1.6) -------------------------------------------------
# A cell is drawn from three layers: the theme palette (colour names), the
# font attached to the cell through styles.xml, and any rich-text runs inside
# the string itself. Only bold / italic / colour are kept — see CellRun.

_NEUTRAL = {"bold": False, "italic": False, "color": None}

# The Office theme colour slots, in the order the ``theme="N"`` attribute
# refers to them. Excel swaps the first four relative to the order they appear
# in ``clrScheme`` (dk1, lt1, dk2, lt2): index 0 is *lt1* (Background 1) and
# index 1 is *dk1* (Text 1), index 2 is lt2 and index 3 is dk2. Getting this
# backwards turns every default black font into white text on a white canvas
# (1.6 bug, reported with a WPS workbook).
_THEME_ORDER = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3",
                "accent4", "accent5", "accent6", "hlink", "folHlink"]

# Both Excel and WPS write ``<color theme="1"/>`` (and occasionally theme="0")
# for the *automatic* font colour on almost every cell. That is not a colour
# the user picked, so it must not override PhyloClear's own label colour. A
# tinted variant of either slot IS a real choice and is kept.
_AUTOMATIC_THEME_SLOTS = (0, 1)
# Used when a workbook ships no theme1.xml (the 2013+ defaults).
_THEME_FALLBACK = {
    "dk1": "#000000", "lt1": "#FFFFFF", "dk2": "#44546A", "lt2": "#E7E6E6",
    "accent1": "#4472C4", "accent2": "#ED7D31", "accent3": "#A5A5A5",
    "accent4": "#FFC000", "accent5": "#5B9BD5", "accent6": "#70AD47",
    "hlink": "#0563C1", "folHlink": "#954F72",
}

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def _flag(node):
    """``<b/>`` is on; ``<b val="0"/>`` is explicitly off."""
    value = node.get("val")
    if value is None:
        return True
    return str(value).strip().lower() not in ("0", "false", "off")


def _argb_to_hex(argb):
    """``FFFF0000`` -> ``#FF0000`` (the leading pair is the alpha channel)."""
    text = (argb or "").strip()
    if len(text) == 8 and text[:2].upper() in ("00", "FF"):
        text = text[2:]
    return "#" + text.upper() if _HEX_RE.match(text) else None


def _apply_tint(hex_color, tint):
    """Brighten (tint > 0) or darken (tint < 0) a theme colour."""
    if not hex_color or abs(tint) < 1e-6:
        return hex_color
    out = []
    shift = int(hex_color.lstrip("#"), 16)
    for component in ((shift >> 16) & 255, (shift >> 8) & 255, shift & 255):
        value = float(component)
        value = value * (1.0 + tint) if tint < 0 else value + (255.0 - value) * tint
        out.append(max(0, min(255, int(round(value)))))
    return "#%02X%02X%02X" % tuple(out)


def _color_value(node, theme=None):
    """Resolve a ``<color>`` element to ``#RRGGBB`` (or ``None``)."""
    if node is None:
        return None
    rgb = _argb_to_hex(node.get("rgb") or "")
    if rgb:
        return rgb
    theme_index = node.get("theme")
    if theme_index is not None:
        try:
            number = int(theme_index)
            slot = _THEME_ORDER[number]
        except (TypeError, ValueError, IndexError):
            return None
        try:
            tint = float(node.get("tint") or 0.0)
        except ValueError:
            tint = 0.0
        if number in _AUTOMATIC_THEME_SLOTS and abs(tint) < 1e-6:
            # "Automatic" text/background colour: leave the label colour to
            # PhyloClear instead of forcing (usually white or black) onto it.
            return None
        base = (theme or _THEME_FALLBACK).get(slot, _THEME_FALLBACK.get(slot))
        return _apply_tint(base, tint)
    # ``indexed`` refers to the legacy 56-colour palette: too rare (and too
    # ambiguous) to bother with, so such cells just keep the default colour.
    return None


def _read_theme(archive, names):
    """Slot name -> hex string, read from the workbook's theme part."""
    key = "xl/theme/theme1.xml"
    if key not in names:
        return dict(_THEME_FALLBACK)
    try:
        root = ET.fromstring(archive.read(key))
    except (ET.ParseError, OSError, KeyError):
        return dict(_THEME_FALLBACK)
    palette = dict(_THEME_FALLBACK)
    for node in root.iter():
        if _localname(node.tag) != "clrScheme":
            continue
        for child in node:
            slot = _localname(child.tag)
            if slot not in _THEME_FALLBACK:
                continue
            for leaf in child.iter():
                name = _localname(leaf.tag)
                # lastClr holds the colour Excel actually rendered.
                value = leaf.get("lastClr") or leaf.get("val")
                if name in ("srgbClr", "sysClr") and value:
                    palette[slot] = "#" + value.strip().lstrip("#").upper()
                    break
        break
    return palette


def _read_styles(archive, names, theme):
    """Traits per cell-format index, i.e. what each ``s="N"`` means."""
    if "xl/styles.xml" not in names:
        return []
    try:
        root = ET.fromstring(archive.read("xl/styles.xml"))
    except (ET.ParseError, OSError, KeyError):
        return []
    fonts = []
    for container in root:
        if _localname(container.tag) == "fonts":
            for node in container:
                if _localname(node.tag) == "font":
                    fonts.append(_font_traits(node, theme))
            break
    out = []
    for container in root:
        if _localname(container.tag) != "cellXfs":
            continue
        for node in container:
            if _localname(node.tag) != "xf":
                continue
            try:
                index = int(node.get("fontId") or 0)
            except ValueError:
                index = 0
            out.append(fonts[index] if 0 <= index < len(fonts) else _NEUTRAL)
    return out


def _font_traits(node, theme=None):
    """``{"bold", "italic", "color"}`` of one ``<font>`` definition.

    Size and family are read nowhere: the tree decides those itself.
    """
    traits = dict(_NEUTRAL)
    for child in node:
        name = _localname(child.tag)
        if name == "b":
            traits["bold"] = _flag(child)
        elif name == "i":
            traits["italic"] = _flag(child)
        elif name == "color":
            traits["color"] = _color_value(child, theme)
    return traits


def _parse_rpr(node, theme=None):
    """Override traits carried by a run's ``<rPr>`` element."""
    traits = {"bold": None, "italic": None, "color": None}
    if node is None:
        return traits
    for child in node:
        name = _localname(child.tag)
        if name == "b":
            traits["bold"] = _flag(child)
        elif name == "i":
            traits["italic"] = _flag(child)
        elif name == "color":
            traits["color"] = _color_value(child, theme)
    return traits


def _string_specs(container, theme=None):
    """``(text, specs)`` for a shared string or an inline string body.

    ``specs`` is ``None`` when the text has a single uniform format; otherwise
    it lists ``(text, override traits)`` per rich-text run. Phonetic runs
    (``<rPh>``, used for Japanese furigana) are skipped — they are hints, not
    content.
    """
    pieces = []
    for child in container:
        name = _localname(child.tag)
        if name == "t":
            pieces.append((child.text or "", None))
        elif name == "r":
            rpr = None
            for sub in child:
                if _localname(sub.tag) == "rPr":
                    rpr = sub
                    break
            override = None if rpr is None else _parse_rpr(rpr, theme)
            for sub in child:
                if _localname(sub.tag) == "t":
                    pieces.append((sub.text or "", override))
    text = "".join(piece for piece, _ in pieces)
    if not any(override is not None for _, override in pieces):
        return text, None
    return text, pieces


def _runs_from_specs(specs, base):
    """Merge rich-text overrides onto the cell's own traits."""
    runs = []
    for text, override in specs:
        traits = dict(base)
        if override:
            for key in ("bold", "italic", "color"):
                if override.get(key) is not None:
                    traits[key] = override[key]
        runs.append(CellRun(text, traits["bold"], traits["italic"],
                            traits["color"]))
    return runs


def _runs_for_text(text, base):
    """One run for a uniformly formatted cell (``None`` when unremarkable)."""
    if not text:
        return None
    return _runs_or_none(_runs_from_specs([(text, None)], base))


# -- Office Open XML -------------------------------------------------------
def _read_xlsx(path, sheet=None, has_header=True):
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise TableError(
            "%s is not a readable workbook (it may be an old .xls/.et file "
            "renamed to .xlsx) — please re-save it as .xlsx" % exc)
    except OSError as exc:
        raise TableError("cannot open %s: %s" % (path, exc))

    with archive:
        names = set(archive.namelist())
        theme = _read_theme(archive, names)
        cell_fonts = _read_styles(archive, names, theme)
        shared, shared_specs = _read_shared_strings(archive, names)
        sheets = _list_sheets(archive, names)
        if not sheets:
            raise TableError("workbook contains no worksheet")

        target, chosen = None, None
        if sheet is not None:
            for name, path_in_zip in sheets:
                if name == sheet:
                    target, chosen = path_in_zip, name
                    break
        if target is None:
            chosen, target = sheets[0]
        if target not in names:
            raise TableError("worksheet '%s' is missing from the file" % target)

        try:
            xml = archive.read(target)
        except KeyError as exc:
            raise TableError("cannot read worksheet: %s" % exc)
    rows, formats = _parse_sheet_xml(xml, shared, shared_specs, cell_fonts)
    return _finish(TableData(path, sheet=chosen,
                             sheets=[s[0] for s in sheets]),
                   rows, has_header, formats)


def _read_shared_strings(archive, names):
    """Return ``([text], [specs])`` for the workbook's shared strings.

    ``specs[i]`` is ``None`` when the whole string shares one format, else a
    list of ``(text, traits)`` pairs describing its rich-text runs.
    """
    key = "xl/sharedStrings.xml"
    if key not in names:
        return [], []
    try:
        root = ET.fromstring(archive.read(key))
    except (ET.ParseError, OSError):
        return [], []
    texts, specs = [], []
    for si in root:
        if _localname(si.tag) != "si":
            continue
        text, spec = _string_specs(si)
        texts.append(text)
        specs.append(spec)
    return texts, specs


def _list_sheets(archive, names):
    """Ordered [(sheet name, zip member)] from workbook.xml + its rels."""
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        try:
            root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        except ET.ParseError:
            root = None
        if root is not None:
            for rel in root:
                rels[rel.get("Id", "")] = rel.get("Target", "")

    order = []
    if "xl/workbook.xml" in names:
        try:
            root = ET.fromstring(archive.read("xl/workbook.xml"))
        except ET.ParseError:
            root = None
        if root is not None:
            rid_attr = None
            for node in root.iter():
                if _localname(node.tag) == "sheet":
                    name = node.get("name") or "Sheet"
                    rid = None
                    for k, v in node.attrib.items():
                        if _localname(k) == "id":
                            rid = v
                            rid_attr = True
                    member = rels.get(rid, "")
                    if member:
                        member = member.lstrip("/")
                        if not member.startswith("xl/"):
                            member = "xl/" + member
                    order.append((name, member))
            del rid_attr

    # Fall back to whatever worksheet parts the archive actually holds (some
    # WPS/3rd-party writers keep a non-standard workbook.xml).
    if not order:
        for name in sorted(n for n in names if n.startswith("xl/worksheets/")
                           and n.endswith(".xml")):
            order.append((os.path.basename(name)[:-4], name))
    # Repair any missing member paths by position.
    fixed = []
    for i, (name, member) in enumerate(order):
        if not member or member not in names:
            guess = "xl/worksheets/sheet%d.xml" % (i + 1)
            if guess in names:
                member = guess
        if member:
            fixed.append((name, member))
    return fixed


def _parse_sheet_xml(xml, shared, shared_specs=None, cell_fonts=None):
    """Extract every cell into a dense list of rows (plus cell formats)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise TableError("damaged worksheet XML: %s" % exc)

    shared_specs = shared_specs or []
    cell_fonts = cell_fonts or []
    rows, formats = [], []
    for row_node in root.iter():
        if _localname(row_node.tag) != "row":
            continue
        cells, cell_runs = {}, {}
        for cell in row_node:
            if _localname(cell.tag) != "c":
                continue
            ref = cell.get("r") or ""
            idx = _col_index(ref) if ref else len(cells)
            value, runs = _cell_text_and_runs(cell, shared, shared_specs,
                                              cell_fonts)
            cells[idx] = value
            cell_runs[idx] = runs
        if not cells:
            rows.append([])
            formats.append([])
            continue
        width = max(cells) + 1
        rows.append([cells.get(i, "") for i in range(width)])
        formats.append([cell_runs.get(i) for i in range(width)])
    # Drop trailing blank rows produced by formatting-only rows.
    while rows and not any(str(v).strip() for v in rows[-1]):
        rows.pop()
        formats.pop()
    return rows, formats


def _cell_value(cell, shared, shared_specs=None, cell_fonts=None):
    """Plain text of one cell (formatting discarded)."""
    text, _runs = _cell_text_and_runs(cell, shared, shared_specs or [],
                                      cell_fonts or [])
    return text


def _cell_text_and_runs(cell, shared, shared_specs, cell_fonts):
    traits = _traits_of_cell(cell, cell_fonts)
    ctype = cell.get("t") or "n"

    if ctype == "inlineStr":
        # The text lives in an <is> container (<c><is><t>x</t></is></c>); a
        # few writers put the runs directly under <c>, so fall back to that.
        body = None
        for child in cell:
            if _localname(child.tag) == "is":
                body = child
                break
        text, specs = _string_specs(body if body is not None else cell)
        return text, _runs(specs, text, traits)

    v = None
    for child in cell:
        if _localname(child.tag) == "v":
            v = child.text or ""
            break

    if ctype == "s":
        try:
            index = int(v)
        except (TypeError, ValueError):
            return "", None
        if not (0 <= index < len(shared)):
            return "", None
        text = shared[index]
        specs = shared_specs[index] if index < len(shared_specs) else None
        return text, _runs(specs, text, traits)

    if ctype == "b":
        return ("TRUE" if v == "1" else "FALSE"), _runs_for_text(
            "TRUE" if v == "1" else "FALSE", traits)
    if ctype == "e":
        return str(v or ""), _runs_for_text(str(v or ""), traits)
    if v is None:
        return "", None
    if ctype == "n" or v != "":
        number = _clean_number(v)
        return number, _runs_for_text(number, traits)
    return "", None


def _runs(specs, text, traits):
    """Rich runs when the string defines any, else one uniform run."""
    if specs is None:
        return _runs_for_text(text, traits)
    return _runs_or_none(_runs_from_specs(specs, traits))


def _runs_or_none(runs):
    """Drop the whole thing when the sheet marked nothing worth drawing."""
    if not runs:
        return None
    if not any(run.formatted for run in runs):
        return None
    return runs


def _traits_of_cell(cell, cell_fonts):
    """The font a cell inherits from its ``s="N"`` format index."""
    index = cell.get("s")
    if index is not None and cell_fonts:
        try:
            return dict(cell_fonts[int(index)])
        except (TypeError, ValueError, IndexError):
            pass
    return dict(_NEUTRAL)


def _clean_number(text):
    """Return numbers the way a human typed them (no float artifacts)."""
    s = str(text).strip()
    if not s:
        return ""
    try:
        value = float(s)
    except ValueError:
        return s
    # Keep scientific notation and genuine fractions as-is, but avoid
    # 0.10000000000000001 style noise.
    if "e" in s.lower():
        return s
    if abs(value - int(value)) < 1e-9 and abs(value) < 1e15:
        return str(int(value))
    return ("%.10f" % value).rstrip("0").rstrip(".")


# -- delimited text --------------------------------------------------------
def _read_text(path, has_header=True):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise TableError("cannot open %s: %s" % (path, exc))
    text = _decode(raw)
    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = []
    for row in reader:
        rows.append([str(cell).strip() for cell in row])
    while rows and not any(v for v in rows[-1]):
        rows.pop()
    data = TableData(path, sheet=None, sheets=[])
    return _finish(data, rows, has_header)


def _decode(raw):
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _detect_delimiter(text):
    head = text[:4096]
    first_line = head.splitlines()[0] if head.splitlines() else ""
    counts = {"\t": first_line.count("\t"), ";": first_line.count(";"),
              ",": first_line.count(",")}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] > 0 else ","


# -- shared post-processing ------------------------------------------------
def _finish(data, rows, has_header, formats=None):
    """Normalise row widths and split off the header row.

    ``formats`` follows exactly the same padding/popping as ``rows`` so that
    ``formats[r][c]`` always describes ``rows[r][c]``.
    """
    width = max((len(r) for r in rows), default=0)
    for row in rows:
        if len(row) < width:
            row.extend([""] * (width - len(row)))
    if formats is not None:
        for line in formats:
            if len(line) < width:
                line.extend([None] * (width - len(line)))
        while len(formats) < len(rows):
            formats.append([None] * width)
        if rows and has_header:
            formats.pop(0)
    if rows and has_header:
        data.headers = rows.pop(0)
    data.rows = rows
    data.has_header = has_header
    data.formats = formats
    return data
