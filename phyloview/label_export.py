"""Export the tip labels of the current tree as TXT, CSV or XLSX.

Only the Python standard library is used (``csv`` / ``zipfile``), so the
feature works inside the one-file executable without shipping openpyxl.

The three formats are deliberately different in what they are for:

``.txt``
    A plain list, one **displayed** label per line — handy as a taxon list.
``.csv`` / ``.xlsx``
    A two-column table: column A is the label as it appears in the tree file
    (the key used by the label-annotation importer), column B is the label
    currently drawn on screen. Such a file can be edited in Excel / WPS and
    imported again straight away, which makes it a ready-made annotation
    template.

CSV is written as UTF-8 with BOM so Excel on Chinese Windows opens the
Chinese labels correctly; XLSX cells are inline strings, so no shared-string
part is needed.
"""

import csv
import os
import zipfile
from xml.sax.saxutils import escape as _xml_escape

SUPPORTED_FORMATS = (".txt", ".csv", ".xlsx")

_DEFAULT_HEADERS = ("Original label", "Displayed label")


class LabelExportError(Exception):
    """Raised when the chosen file cannot be written."""


def format_from_path(path, selected_filter=""):
    """Return one of ``.txt`` / ``.csv`` / ``.xlsx`` for a save-dialog result.

    An explicit extension always wins. When the user typed a name without an
    extension, the filter they picked in the dialog decides the format.
    """
    ext = os.path.splitext(path or "")[1].lower()
    if ext in SUPPORTED_FORMATS:
        return ext
    filt = (selected_filter or "").lower()
    for candidate in SUPPORTED_FORMATS:
        if "*" + candidate in filt or candidate.lstrip(".") + ")" in filt:
            return candidate
    # "Text files (*.txt)" etc. also match a bare extension mention.
    for candidate in SUPPORTED_FORMATS:
        if candidate in filt:
            return candidate
    return ".txt"


def normalise_path(path, selected_filter=""):
    """Append the extension implied by the chosen filter when it is missing."""
    fmt = format_from_path(path, selected_filter)
    ext = os.path.splitext(path or "")[1].lower()
    if ext not in SUPPORTED_FORMATS:
        path = (path or "labels") + fmt
    return path, fmt


def export_labels(path, rows, fmt=None, headers=_DEFAULT_HEADERS):
    """Write ``rows`` (iterable of ``(original, displayed)`` pairs) to ``path``.

    ``fmt`` defaults to the file extension. Returns the path actually written.
    """
    rows = [(str(a or ""), str(b if b is not None else a or ""))
            for a, b in rows]
    fmt = (fmt or os.path.splitext(path)[1].lower() or ".txt").lower()
    if fmt not in SUPPORTED_FORMATS:
        raise LabelExportError("unsupported label format: %s" % fmt)
    try:
        if fmt == ".txt":
            _write_txt(path, rows)
        elif fmt == ".csv":
            _write_csv(path, rows, headers)
        else:
            _write_xlsx(path, rows, headers)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise LabelExportError(str(exc)) from exc
    return path


def _write_txt(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for _original, displayed in rows:
            fh.write(displayed.replace("\r", " ").replace("\n", " ") + "\n")


def _write_csv(path, rows, headers):
    # utf-8-sig makes Excel/WPS on Chinese Windows read the labels correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(headers))
        for original, displayed in rows:
            writer.writerow([original, displayed])


# -- minimal OOXML workbook -------------------------------------------------
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="%s">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""" % _CONTENT_NS

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="%s">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""" % _PKG_REL_NS

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="%s" xmlns:r="%s">
<sheets><sheet name="Labels" sheetId="1" r:id="rId1"/></sheets>
</workbook>""" % (_MAIN_NS, _REL_NS)

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="%s">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""" % _PKG_REL_NS

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="%s">
<fonts count="2">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
</fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
</styleSheet>""" % _MAIN_NS


def _clean(value):
    """XML-safe text (Excel rejects most C0 control characters)."""
    return "".join(ch for ch in str(value)
                   if ch == "\t" or ch == "\n" or ch == "\r"
                   or ord(ch) >= 32)


def _cell(ref, text, style=0):
    body = _xml_escape(_clean(text))
    return ('<c r="%s" t="inlineStr" s="%d"><is><t xml:space="preserve">%s'
            '</t></is></c>' % (ref, style, body))


def _col_letter(index):
    letters = ""
    index = max(0, index)
    while True:
        letters = chr(ord("A") + index % 26) + letters
        index = index // 26 - 1
        if index < 0:
            return letters


def _sheet_xml(rows, headers):
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="%s">' % _MAIN_NS,
        '<dimension ref="A1:B%d"/>' % (len(rows) + 1),
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        '<cols><col min="1" max="1" width="30" customWidth="1"/>'
        '<col min="2" max="2" width="40" customWidth="1"/></cols>',
        '<sheetData>',
    ]
    header = ['<row r="1">']
    for col, text in enumerate(headers[:2]):
        header.append(_cell("%s1" % _col_letter(col), text, style=1))
    header.append('</row>')
    parts.append("".join(header))
    for r, row in enumerate(rows, start=2):
        cells = ['<row r="%d">' % r]
        for col, text in enumerate(row[:2]):
            cells.append(_cell("%s%d" % (_col_letter(col), r), text))
        cells.append('</row>')
        parts.append("".join(cells))
    parts.append('</sheetData></worksheet>')
    return "".join(parts)


def _write_xlsx(path, rows, headers):
    members = (
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("_rels/.rels", _ROOT_RELS),
        ("xl/workbook.xml", _WORKBOOK),
        ("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS),
        ("xl/styles.xml", _STYLES),
        ("xl/worksheets/sheet1.xml", _sheet_xml(rows, headers)),
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in members:
            archive.writestr(name, body.encode("utf-8"))
