"""File-format detection and unified loading helpers."""

from .newick import parse_newick, parse_newick_string
from .nexus import parse_nexus, parse_nexus_string

NEXUS = "nexus"
NEWICK = "newick"

_EXT_MAP = {
    ".nwk": NEWICK,
    ".newick": NEWICK,
    ".tre": NEWICK,
    ".tree": NEWICK,
    ".nex": NEXUS,
    ".nexus": NEXUS,
    ".nxs": NEXUS,
    ".phy": NEWICK,
    # IQ-TREE writes *.treefile (and sometimes *.phy.treefile); it is plain
    # Newick, so unknown extensions already fall back to NEWICK below.
    ".treefile": NEWICK,
    ".contree": NEWICK,
}


def detect_format(text):
    """Detect the format of tree text content."""
    stripped = text.lstrip()
    if stripped.lower().startswith("#nexus"):
        return NEXUS
    return NEWICK


def load_tree_string(text):
    """Parse tree text, auto-detecting Newick vs Nexus.

    Returns a list of :class:`Tree` (Nexus may hold several trees).
    """
    if detect_format(text) == NEXUS:
        return parse_nexus_string(text)
    return [parse_newick_string(text)]


def load_tree_file(path):
    """Load tree(s) from a file, auto-detecting format."""
    fmt = detect_format_by_extension(path)
    if fmt == NEXUS:
        return parse_nexus(path)
    return [parse_newick(path)]


def detect_format_by_extension(path):
    import os

    ext = os.path.splitext(path)[1].lower()
    if ext in (".nex", ".nexus", ".nxs"):
        return NEXUS
    return NEWICK
