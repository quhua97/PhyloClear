"""Nexus format parser (TAXA and TREES blocks).

Supports the common subset of NEXUS used for phylogenetic trees:
  * #NEXUS header
  * BEGIN TREES; ... END;
  * TRANSLATE <number> <name>, ... ;
  * TREE <name> = [&R] <newick> ;
  * [&R] / [&U] annotations and [comments]
"""

import re

from ..tree_model import Tree
from .newick import NewickError, parse_newick_string

_BLOCK_RE = re.compile(r"(?i)\bbegin\s+(\w+)\s*;")
_END_RE = re.compile(r"(?i)\bend\s*;")
_TRANSLATE_RE = re.compile(
    r"(?i)\btranslate\s*([^;]*?)\s*;", re.DOTALL
)
_TREE_CMD_RE = re.compile(
    r"(?i)\btree\s+(\*)?\s*([^=\s]+)\s*=\s*(.*?)(?=\btree\b|\bend\s*;|\Z)",
    re.DOTALL,
)


def _strip_comments(text):
    """Remove NEXUS [...] comments (no nesting is handled here)."""
    out = []
    depth = 0
    for ch in text:
        if ch == "[":
            depth += 1
            continue
        if ch == "]":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _parse_translate(body):
    """Return a dict {number: name} from a TRANSLATE statement body."""
    mapping = {}
    tokens = re.findall(r"(\d+)\s+([^,\s]+|'[^']*'|\"[^\"]*\")", body)
    for num, name in tokens:
        name = name.strip("'\"")
        mapping[int(num)] = name
    return mapping


def parse_nexus_string(text):
    """Parse NEXUS text and return a list of :class:`Tree` objects."""
    text = text.strip()
    if not text:
        raise NewickError("Empty NEXUS content.")

    # Locate TREES blocks.
    trees = []
    for block_match in _BLOCK_RE.finditer(text):
        block_name = block_match.group(1).upper()
        if block_name not in ("TREES", "TREE"):
            continue
        start = block_match.end()
        end_match = _END_RE.search(text, start)
        block = text[start : end_match.start() if end_match else len(text)]
        trees.extend(_parse_trees_block(block))

    if not trees:
        # Maybe the content is actually a bare Newick string.
        try:
            return [parse_newick_string(text)]
        except NewickError:
            raise NewickError("No TREES block found in NEXUS content.")
    return trees


def _parse_trees_block(block):
    """Parse a TREES block body into a list of trees."""
    trees = []

    # Translate mapping
    translate = {}
    tm = _TRANSLATE_RE.search(block)
    if tm:
        translate = _parse_translate(tm.group(1))

    # Tree commands
    for cm in _TREE_CMD_RE.finditer(block):
        name = cm.group(2)
        newick = cm.group(3)
        newick = _strip_comments(newick)
        # strip a leading [&R] or [&U] annotation (already removed by comments)
        newick = newick.strip()
        # The tree statement ends at a semicolon that closes the newick string.
        tree = _parse_single_tree(name, newick, translate)
        if tree is not None:
            trees.append(tree)

    # Fallback: if regex missed, look for any newick in the block.
    if not trees:
        tree = _parse_single_tree("tree", block, translate)
        if tree is not None:
            trees.append(tree)

    return trees


def _parse_single_tree(name, newick, translate):
    """Parse one newick expression, applying a TRANSLATE mapping."""
    newick = newick.strip()
    if not newick or newick.startswith("*"):
        newick = newick.lstrip("*").strip()
    # Cut at the first top-level ';' (the newick terminator).
    semicolon = _find_newick_terminator(newick)
    if semicolon is None:
        return None
    newick = newick[: semicolon + 1]

    try:
        tree = parse_newick_string(newick)
    except NewickError:
        return None

    # Apply translate mapping to integer leaf labels (post-parse, safe).
    if translate:
        for leaf in tree.leaves:
            if leaf.name and str(leaf.name).strip().isdigit():
                mapped = translate.get(int(leaf.name))
                if mapped:
                    leaf.name = mapped

    tree.name = name if name else None
    return tree


def _find_newick_terminator(text):
    """Find the index of the ';' that terminates the newick string."""
    depth = 0
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            return i
    return None


def parse_nexus(path):
    """Read and parse a NEXUS file."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse_nexus_string(fh.read())
