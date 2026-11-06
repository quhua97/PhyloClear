"""Newick / New Hampshire tree format parser.

A recursive-descent parser supporting:
  * nested subtrees
  * quoted labels (single or double quotes)
  * comments in square brackets
  * branch lengths (":1.23")
  * branch lengths as "[&length=1.23]" annotations
  * internal node labels (support values)
  * IQ-TREE dual support labels such as "100/100"
  * QuartetScores annotations such as
    "[qp-ic:0.761628;lq-ic:0.692567;eqp-ic:0.761628]"
  * the trailing ";" terminator
"""

import re

from ..tree_model import Tree, Node

# Matches a "length=<number>" key inside a Nexus/Newick [&...] annotation.
_LENGTH_RE = re.compile(r"(?i)length\s*=\s*([0-9.eE+-]+)")

_NUMBER = r"[-+]?(?:[0-9]*\.[0-9]+|[0-9]+\.?)(?:[eE][-+]?[0-9]+)?"
# key:value or key=value pairs in a Newick square-bracket comment.
_METRIC_RE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)\s*[:=]\s*(" + _NUMBER + r")")
_SLASH_ITEM_RE = re.compile(r"^\s*(" + _NUMBER + r")\s*$")
# Reserved NHX/Newick annotation keys that are not support metrics.
_NON_METRIC_KEYS = {"length", "label", "name", "color", "r", "u"}

# Display order + human readable names for the support metrics this build
# knows about. Unknown keys found in a file are appended alphabetically and
# shown with their own name, so future QuartetScores columns still work.
SUPPORT_FIELD_LABELS = [
    ("original", "Original tree support"),
    ("qp-ic", "QP-IC"),
    ("lq-ic", "LQ-IC"),
    ("eqp-ic", "EQP-IC"),
    ("s1", "Support 1 (before /)"),
    ("s2", "Support 2 (after /)"),
    ("s3", "Support 3"),
    ("s4", "Support 4"),
    ("s5", "Support 5"),
    ("s6", "Support 6"),
]


class NewickError(ValueError):
    pass


class _Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.n = len(text)

    # -- low-level helpers -------------------------------------------------
    def _peek(self):
        return self.text[self.pos] if self.pos < self.n else ""

    def _skip_ws(self):
        while self.pos < self.n and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def _skip_comment(self):
        # assumes self.text[self.pos] == '['
        depth = 0
        while self.pos < self.n:
            c = self.text[self.pos]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return
            self.pos += 1

    def _read_comments(self):
        """Consume the square-bracket comment(s) following a node and return
        their combined text (without the brackets).

        QuartetScores writes ``)100:0.106124[qp-ic:...;lq-ic:...]``: the
        comment belongs to the *internal node* just closed, so it must be
        picked up here rather than discarded by the parent's skip loop.
        Nested brackets are supported, like in _skip_comment().
        """
        self._skip_ws()
        chunks = []
        while self._peek() == "[":
            depth = 0
            start = self.pos + 1
            closed = False
            while self.pos < self.n:
                c = self.text[self.pos]
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        chunks.append(self.text[start:self.pos])
                        self.pos += 1
                        closed = True
                        break
                self.pos += 1
            if not closed:
                break
            self._skip_ws()
        return ";".join(chunks)

    def _read_token(self):
        """Read a label token (quoted or bare), stopping at structural chars."""
        self._skip_ws()
        if self.pos >= self.n:
            return ""
        c = self.text[self.pos]
        if c in "(),:;":
            return ""
        if c in "'\"":
            return self._read_quoted(c)
        start = self.pos
        while self.pos < self.n:
            ch = self.text[self.pos]
            if ch in "(),:;[] \t\r\n":
                break
            self.pos += 1
        return self.text[start:self.pos]

    def _read_quoted(self, quote):
        self.pos += 1  # skip opening quote
        chars = []
        while self.pos < self.n:
            c = self.text[self.pos]
            if c == quote:
                # doubled quote = escaped literal quote
                if self.pos + 1 < self.n and self.text[self.pos + 1] == quote:
                    chars.append(quote)
                    self.pos += 2
                    continue
                self.pos += 1
                break
            chars.append(c)
            self.pos += 1
        return "".join(chars)

    def _read_branch_length(self):
        # assumes self.text[self.pos] == ':'
        self.pos += 1
        self._skip_ws()
        start = self.pos
        while self.pos < self.n and self.text[self.pos] in "0123456789.+-eE":
            self.pos += 1
        raw = self.text[start:self.pos]
        if raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _try_read_length_annotation(self):
        """If a "[&length=X]" annotation follows, consume it and return X."""
        if self._peek() != "[":
            return None
        end = self.text.find("]", self.pos)
        if end == -1:
            return None
        content = self.text[self.pos + 1:end]
        m = _LENGTH_RE.search(content)
        if not m:
            return None
        self.pos = end + 1
        try:
            return float(m.group(1))
        except ValueError:
            return None

    # -- recursive descent --------------------------------------------------
    def _parse_node(self):
        self._skip_ws()
        while self._peek() == "[":
            self._skip_comment()
            self._skip_ws()

        if self._peek() == "(":
            return self._parse_internal()

        # leaf node
        name = self._read_token()
        node = Node(name=name or None)
        node._is_leaf = True
        self._skip_ws()
        if self._peek() == ":":
            node.branch_length = self._read_branch_length()
        else:
            bl = self._try_read_length_annotation()
            if bl is not None:
                node.branch_length = bl
        return node

    def _parse_internal(self):
        # assumes self.text[self.pos] == '('
        self.pos += 1
        children = []
        while True:
            self._skip_ws()
            while self._peek() == "[":
                self._skip_comment()
                self._skip_ws()
            child = self._parse_node()
            children.append(child)
            self._skip_ws()
            while self._peek() == "[":
                self._skip_comment()
                self._skip_ws()
            c = self._peek()
            if c == ",":
                self.pos += 1
                continue
            if c == ")":
                self.pos += 1
                break
            if c == "":
                raise NewickError("Unexpected end of input inside subtree.")

        node = Node()
        for child in children:
            node.add_child(child)

        self._skip_ws()
        # internal label -> support value
        label = self._read_token()
        if label:
            node.support = _coerce_support(label)
            node.name = label
            # IQ-TREE writes two (or more) support values separated by "/",
            # e.g. "100/100" = SH-aLRT / ultrafast bootstrap. Keep the raw
            # label in node.support and expose each part as its own metric.
            slash_values = _split_slash_support(label)
            if slash_values is not None:
                for i, value in enumerate(slash_values, 1):
                    node.support_metrics["s%d" % i] = value
            else:
                node.support_metrics["original"] = node.support
        self._skip_ws()
        if self._peek() == ":":
            node.branch_length = self._read_branch_length()
        else:
            bl = self._try_read_length_annotation()
            if bl is not None:
                node.branch_length = bl
        # QuartetScores puts qp-ic / lq-ic / eqp-ic in a bracket comment that
        # follows the branch length. Capture it for this very node.
        comment = self._read_comments()
        if comment:
            node.support_metrics.update(_parse_annotation_metrics(comment))
        return node


def _coerce_support(label):
    """Try to interpret an internal label as a numeric support value."""
    s = label.strip()
    try:
        return float(s)
    except ValueError:
        return label


def _split_slash_support(label):
    """Return [float, ...] for "100/100"-style labels, else None."""
    if "/" not in label:
        return None
    parts = label.split("/")
    if not 2 <= len(parts) <= 6:
        return None
    values = []
    for part in parts:
        m = _SLASH_ITEM_RE.match(part)
        if not m:
            return None
        values.append(float(m.group(1)))
    return values


def _parse_annotation_metrics(comment):
    """Extract numeric key:value / key=value metrics from a bracket comment."""
    metrics = {}
    for match in _METRIC_RE.finditer(comment):
        key = match.group(1).lower()
        if key in _NON_METRIC_KEYS:
            continue
        try:
            metrics[key] = float(match.group(2))
        except ValueError:
            continue
    return metrics


def support_fields_for(tree):
    """Ordered [(key, English label)] of support metrics present in ``tree``."""
    found = set()
    for node in tree.nodes:
        if node.is_internal:
            found.update((getattr(node, "support_metrics", None) or {}).keys())
    fields = [(key, label) for key, label in SUPPORT_FIELD_LABELS if key in found]
    known = {key for key, _ in SUPPORT_FIELD_LABELS}
    for key in sorted(found - known):
        fields.append((key, key.upper()))
    return fields


def parse_newick_string(text):
    """Parse a Newick string into a :class:`Tree`."""
    text = text.strip()
    if not text:
        raise NewickError("Empty Newick string.")
    p = _Parser(text)
    root = p._parse_node()

    def _skip_trailing():
        p._skip_ws()
        while p._peek() == "[":
            p._skip_comment()
            p._skip_ws()

    _skip_trailing()
    if p._peek() == ";":
        p.pos += 1
    _skip_trailing()
    if p.pos < p.n:
        raise NewickError("Trailing characters after tree at position %d." % p.pos)
    tree = Tree(root=root)
    tree.index_nodes()
    tree.support_fields = support_fields_for(tree)
    return tree


def parse_newick(path):
    """Read and parse a Newick file (UTF-8 with fallback)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse_newick_string(fh.read())
