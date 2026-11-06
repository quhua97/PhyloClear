"""Core tree data model for PhyloClear."""

import re

# Characters that force a label to be quoted in Newick output.
# "/" is deliberately NOT here: IQ-TREE writes dual support values such as
# "100/100" as a bare internal label, and it is a legal Newick character.
_NEED_QUOTE_RE = re.compile(r"[(),:;\[\]\s'\"=]")


def _quote_label(name):
    """Return a Newick-safe label, quoting if it contains special characters."""
    name = "" if name is None else str(name)
    if name == "":
        return ""
    if _NEED_QUOTE_RE.search(name):
        return "'" + name.replace("'", "''") + "'"
    return name


def _format_number(value):
    """Format a float compactly for Newick (trailing zeros stripped)."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = ("%.8g" % value)
    if "e" not in text and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_support(value):
    """Format an internal-node label (numeric support or a name)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _format_number(value)
    return _quote_label(value)


class Node:
    """A single node in a phylogenetic tree."""

    __slots__ = (
        "name",
        "branch_length",
        "support",
        # 1.8: every support value carried by an internal node, keyed by a
        # stable id ("original", "s1"/"s2" for IQ-TREE's a/b labels, or the
        # QuartetScores metric names qp-ic / lq-ic / eqp-ic). See
        # tree.newick.SUPPORT_FIELD_LABELS for the display order.
        "support_metrics",
        "parent",
        "children",
        "annotations",
        "style",
        "index",
        "_x",
        "_y",
        "_dist",
        "_is_leaf",
        # Collapse/expand state: when True the clade is drawn as a triangle
        # (see rendering.renderer.TreeRenderer). ``collapse_label`` overrides
        # the text printed next to the triangle.
        "collapsed",
        "collapse_label",
    )

    def __init__(self, name=None, branch_length=None, support=None, parent=None):
        self.name = name
        self.branch_length = branch_length
        # support value: bootstrap proportion / posterior probability etc.
        # This remains the *original* internal label, so older code (and the
        # Newick exporter) keeps working unchanged.
        self.support = support
        # Parallel per-metric values, filled in by the Newick parser.
        self.support_metrics = {}
        self.parent = parent
        self.children = []
        self.annotations = {}
        # per-node style overrides: e.g. {"color": "#ff0000", "label": "..."}
        self.style = {}
        self.index = -1
        self._x = 0.0
        self._y = 0.0
        self._dist = 0.0
        self._is_leaf = False
        # Collapse/expand state (see Tree.set_collapsed / expand_all).
        self.collapsed = False
        self.collapse_label = None

    # -- structural helpers -------------------------------------------------
    @property
    def is_leaf(self):
        return len(self.children) == 0

    @property
    def is_root(self):
        return self.parent is None

    @property
    def n_leaves(self):
        """Clade size: the number of terminal (leaf) descendants."""
        return sum(1 for _ in self.iter_leaves())

    @property
    def is_internal(self):
        # Internal node = a branching point (has descendants). This includes
        # the root and excludes leaves, per the user's definition.
        return len(self.children) > 0

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

    # -- layout / rendering state ------------------------------------------
    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = value

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        self._y = value

    # -- traversal ---------------------------------------------------------
    def iter_leaves(self):
        if self.is_leaf:
            yield self
        else:
            for child in self.children:
                yield from child.iter_leaves()

    def iter_nodes(self, order="preorder"):
        """Yield all nodes in the subtree rooted here."""
        if order == "preorder":
            yield self
            for child in self.children:
                yield from child.iter_nodes(order)
        else:  # postorder
            for child in self.children:
                yield from child.iter_nodes(order)
            yield self

    def __repr__(self):
        label = self.name if self.name else ("#%d" % self.index)
        return "<Node %s>" % label


class Tree:
    """A phylogenetic tree."""

    def __init__(self, root=None, name=None):
        self.root = root
        self.name = name
        self.nodes = []  # all nodes, postorder (leaves first)
        # Snapshot of the child order as read from the file (see
        # snapshot_order / restore_order) so "default" branch ordering can put
        # the original arrangement back after a sort.
        self.base_order = []
        # 1.8: ordered [(key, English label)] of the support metrics present
        # in this tree. One entry = a plain tree (nothing to choose); several
        # entries make the "Support Values" panel show checkboxes.
        self.support_fields = []

    def index_nodes(self):
        """Rebuild the node list and assign postorder indices."""
        self.nodes = []
        if self.root is None:
            return
        for i, node in enumerate(self.root.iter_nodes(order="postorder")):
            node.index = i
            self.nodes.append(node)

    @property
    def leaves(self):
        return [n for n in self.nodes if n.is_leaf]

    @property
    def n_taxa(self):
        return sum(1 for n in self.nodes if n.is_leaf)

    def to_newick(self, label_map=None):
        """Serialize the tree to Newick, preserving name/support/branch length.

        User edits (leaf names, support values, branch lengths) are written
        back. Annotations are emitted as ``[&label="..."]`` comments (best
        effort; they are not re-imported by PhyloClear's own parser).

        ``label_map`` optionally maps the original tip label to a replacement
        (used by the 1.5 label table so an exported Newick carries the same
        labels that are drawn on screen).
        """
        label_map = label_map or {}

        def rec(node):
            if node.is_leaf:
                name = node.name
                if name in label_map:
                    name = label_map[name]
                body = _quote_label(name)
            else:
                inner = ",".join(rec(c) for c in node.children)
                label = ""
                if node.support is not None:
                    label = _format_support(node.support)
                elif node.name:
                    label = _quote_label(node.name)
                body = "(" + inner + ")" + label

            ann = node.annotations.get("annotation")
            if ann:
                body += "[&label=\"%s\"]" % str(ann).replace('"', "'")
            if node.branch_length is not None:
                body += ":" + _format_number(node.branch_length)
            # 1.8: QuartetScores stores its three IC scores in a square
            # bracket comment *after* the branch length. Write them back so
            # an exported tree still carries the values it was opened with.
            metrics = getattr(node, "support_metrics", {}) or {}
            ic_keys = [k for k in ("qp-ic", "lq-ic", "eqp-ic") if k in metrics]
            if ic_keys:
                pieces = []
                for key in ic_keys:
                    value = metrics[key]
                    text = (_format_number(value)
                            if isinstance(value, (int, float)) and not isinstance(value, bool)
                            else str(value))
                    pieces.append("%s:%s" % (key, text))
                body += "[" + ";".join(pieces) + "]"
            return body

        return rec(self.root) + ";\n"

    # -- branch ordering ---------------------------------------------------
    def order_clades(self, descending=False):
        """Sort the children of every internal node by clade size (ladderize).

        "Branch ordering — sort clades ascending or descending by clade size":
        at each branching point the child clade with fewer tips comes first
        when ``descending`` is False, and the largest clade first when it is
        True. This only permutes children; topology and branch lengths are
        untouched, and every clade stays monophyletic.
        """
        changed = False
        for node in self.nodes:
            if len(node.children) > 1:
                before = list(node.children)
                node.children.sort(key=lambda c: c.n_leaves, reverse=descending)
                if [id(c) for c in node.children] != [id(c) for c in before]:
                    changed = True
        return changed

    def snapshot_order(self):
        """Remember the current (file) child order for :meth:`restore_order`."""
        self.base_order = [(n, list(n.children)) for n in self.nodes
                           if len(n.children) > 1]

    def restore_order(self):
        """Put the child order captured by :meth:`snapshot_order` back.

        Entries whose children no longer match the snapshot are skipped, so
        this stays safe after rerooting / node edits.
        """
        changed = False
        for node, children in getattr(self, "base_order", []):
            if len(node.children) != len(children):
                continue
            if set(id(c) for c in node.children) != set(id(c) for c in children):
                continue
            if [id(c) for c in node.children] != [id(c) for c in children]:
                node.children = list(children)
                changed = True
        return changed

    # -- rotation ----------------------------------------------------------
    def rotate(self, node):
        """Flip (rotate) ``node``: reverse the order of its immediate children.

        Definition (as specified): "Rotation — flip individual nodes or entire
        subtrees". Because each child of a node is itself an entire subtree,
        reversing the child list flips those subtrees top-to-bottom: the clade
        that used to be drawn uppermost becomes the lowermost one (and vice
        versa for a bifurcating node). Nothing else changes — topology, branch
        lengths and every clade's membership stay exactly the same, so this is
        purely a display operation (the standard FigTree "Rotate" behaviour).

        Returns True when something actually moved.
        """
        if node is None or len(node.children) < 2:
            return False
        node.children.reverse()
        return True

    # -- collapse / expand -------------------------------------------------
    def set_collapsed(self, node, collapsed=True, label=None):
        """Collapse/expand one clade.

        A collapsed clade is drawn as a triangle (wedge) instead of its
        internal structure. Only internal nodes can be collapsed — collapsing
        a tip has no meaning. ``label`` optionally sets the triangle's text.
        """
        if node is None or node.is_leaf:
            return False
        collapsed = bool(collapsed)
        changed = (node.collapsed != collapsed)
        node.collapsed = collapsed
        if label is not None:
            if node.collapse_label != label:
                node.collapse_label = label
                changed = True
        return changed

    def set_collapse_label(self, node, label):
        """Set the text printed next to a collapsed clade's triangle."""
        if node is None:
            return False
        label = label or None
        if node.collapse_label == label:
            return False
        node.collapse_label = label
        return True

    def expand_all(self):
        """Expand every collapsed clade in the tree."""
        changed = False
        for node in self.nodes:
            if node.collapsed:
                node.collapsed = False
                changed = True
        return changed

    def collapsed_nodes(self):
        """Return every collapsed clade, ordered root-most first."""
        out = []
        for node in self.root.iter_nodes(order="preorder") if self.root else []:
            if node.collapsed and not node.is_leaf:
                out.append(node)
        return out

    def is_hidden(self, node):
        """True when ``node`` sits inside a collapsed clade (so not drawn).

        The collapsed node itself IS drawn (as a triangle); its descendants
        are not. Any node below a *nested* collapsed clade is hidden too.
        """
        parent = node.parent
        while parent is not None:
            if parent.collapsed:
                return True
            parent = parent.parent
        return False

    # -- rerooting ---------------------------------------------------------
    @staticmethod
    def _suppress_unary(node):
        """Splice out ``node`` when it is a redundant degree-2 node.

        Rerooting leaves the *former* root with a single child (the child that
        used to lead to the new root becomes its parent), which is a redundant
        degree-2 node with no meaning in a tree figure. ``ape::root`` and
        Biopython's ``root_with_outgroup`` both delete it ("if the original root
        is bifurcating, it is removed"); we do the same and merge the two edge
        lengths. Nodes that carry a name or a support value are kept so no
        information is lost.
        """
        if node is None or node.parent is None or len(node.children) != 1:
            return False
        if node.support is not None or node.name:
            return False
        child = node.children[0]
        parent = node.parent
        if node.branch_length is None and child.branch_length is None:
            merged = None
        else:
            merged = (node.branch_length or 0.0) + (child.branch_length or 0.0)
        parent.children[parent.children.index(node)] = child
        child.parent = parent
        child.branch_length = merged
        node.parent = None
        node.children = []
        return True

    def reroot(self, node, frac=0.5):
        """Reroot the tree on the branch leading to ``node``.

        A new root is created on that branch at fraction ``frac`` of its length
        from ``node`` (0.5 = midpoint). ``node`` becomes one child of the new
        root; the rest of the tree (everything above the cut) is reversed and
        becomes the other child. Branch lengths on the cut edge are split and
        every other edge length is preserved by transferring it to the new
        child that now carries it.

        If ``node`` is already the root, this is a no-op.
        """
        if node is None or node.parent is None:
            return  # already the root
        frac = max(0.0, min(1.0, frac))
        old_root = self.root
        parent = node.parent
        parent_up = parent.parent  # original up-neighbour of `parent` (may be None)
        cut_length = node.branch_length

        # Snapshot original parent pointers and branch lengths. Edge lengths are
        # stored on the child node, so these maps let us transfer lengths
        # correctly after we reverse the path above the cut.
        orig_parent = {n: n.parent for n in self.nodes}
        orig_bl = {n: n.branch_length for n in self.nodes}

        # Detach the down side (`node`) from its parent.
        parent.children.remove(node)
        node.parent = None

        # Build the new root spanning the two sides of the cut. The cut edge is
        # split: new_root -> node (length L*frac) and new_root -> parent
        # (length L*(1-frac)).
        new_root = Node()
        new_root.children = [node, parent]
        node.parent = new_root
        node.branch_length = (cut_length * frac) if cut_length is not None else None
        parent.parent = new_root
        parent.branch_length = (cut_length * (1.0 - frac)) if cut_length is not None else None

        if parent_up is None:
            # `parent` was the old root: nothing above the cut to reverse.
            self.root = new_root
            # `parent` (the old root) may now be a redundant degree-2 node.
            self._suppress_unary(parent)
            self.index_nodes()
            return

        # Reverse the chain from `parent_up` up to the old root. Each node on
        # the path gets a new parent equal to the node below it, and its branch
        # length becomes the length of that edge (originally stored on the
        # child, i.e. orig_bl[down_neighbour]).
        parent_up.parent = parent
        if parent in parent_up.children:
            parent_up.children.remove(parent)  # `parent` is now its parent
        if parent_up not in parent.children:
            parent.children.append(parent_up)  # parent_up becomes child of parent
        parent_up.branch_length = orig_bl[parent]  # edge (parent_up, parent)

        u = parent_up
        while True:
            v = orig_parent[u]  # original up-neighbour of u (None at old root)
            if v is None:
                break
            # v becomes a child of u (reversed): drop the old parent->child
            # link and adopt v beneath u.
            v.parent = u
            if v not in u.children:
                u.children.append(v)
            if u in v.children:
                v.children.remove(u)
            v.branch_length = orig_bl[u]  # edge (v, u) now carried by v
            u = v

        self.root = new_root
        # The former root is left with a single child after the reversal; drop
        # that redundant degree-2 node (standard behaviour of ape / Biopython).
        self._suppress_unary(old_root)
        self.index_nodes()

    def reroot_at_node(self, node):
        """Reroot the tree so that ``node`` ITSELF becomes the new root.

        The whole branch leading to ``node`` is absorbed into the up-side: the
        selected node loses its incoming edge and inherits the root position,
        while the chain above it is reversed beneath it. Every branch length is
        conserved (the absorbed edge length is simply moved onto the up-side's
        new incoming edge).

        NOTE: because an internal node of a bifurcating tree has three
        neighbours, making it the root leaves it with three children — i.e. a
        **basal polytomy** that dissolves the clade (its two original children
        and the whole former up-side all become separate children of the root).
        The UI's root action therefore uses :meth:`reroot` (rooting *along the
        branch* above the clade) instead, which keeps the clade monophyletic and
        yields a resolved, bifurcating root. If ``node`` is already the root,
        this is a no-op.
        """
        if node is None or node.parent is None:
            return  # already the root
        # Snapshot original parents and branch lengths. Edge lengths are stored
        # on the child node, so these maps let us transfer each length onto the
        # node that now carries it after the reversal.
        orig_parent = {}
        orig_bl = {}
        stack = [self.root]
        while stack:
            n = stack.pop()
            orig_parent[n] = n.parent
            orig_bl[n] = n.branch_length
            for c in n.children:
                stack.append(c)

        parent = node.parent
        # Detach `node` from its (old) parent and make it the new root.
        if parent is not None and node in parent.children:
            parent.children.remove(node)
        node.parent = None
        node.branch_length = None

        # Walk the chain from `parent` up to the old root, reversing it so it
        # hangs beneath `node`. `prev` is the node directly below `curr`.
        prev = node
        curr = parent
        while curr is not None:
            # Sever the original link: remove `curr` from its *original* parent's
            # children list, otherwise `curr` would remain listed under both its
            # old and new parents and create a cycle.
            old_p = orig_parent[curr]
            if old_p is not None and curr in old_p.children:
                old_p.children.remove(curr)
            nxt = orig_parent[curr]  # original up-neighbour (None at old root)
            curr.parent = prev
            if curr not in prev.children:
                prev.children.append(curr)
            # The edge between prev and curr keeps its original length; because
            # prev was originally a child of curr, that length is stored on prev
            # (orig_bl[prev]) and is now carried by curr (the new child).
            curr.branch_length = orig_bl[prev]
            prev = curr
            curr = nxt

        self.root = node
        self.index_nodes()

    def _weighted_distances(self, start):
        """Return (dist, pred) dicts for an undirected traversal of the tree.

        Edge lengths are taken from the rooted representation: the length of
        an edge between parent ``p`` and child ``c`` is ``c.branch_length``.
        """
        dist = {start: 0.0}
        pred = {start: None}
        stack = [start]
        while stack:
            u = stack.pop()
            du = dist[u]
            neighbours = list(u.children)
            if u.parent is not None:
                neighbours.append(u.parent)
            for v in neighbours:
                if v in dist:
                    continue
                if v.parent is u:
                    w = v.branch_length if v.branch_length is not None else 0.0
                else:  # u is the child of v
                    w = u.branch_length if u.branch_length is not None else 0.0
                dist[v] = du + w
                pred[v] = u
                stack.append(v)
        return dist, pred

    def midpoint_root(self):
        """Root the tree at the midpoint of the longest path.

        Definition (as specified): "find the root at the midpoint of the
        longest path". The longest path is the tree diameter — the longest
        tip-to-tip path — found by a double sweep of weighted distances. The
        root is placed on whichever edge that path's midpoint falls on, split
        at the midpoint. Rooting lands *on* the edge (never on an existing
        node) so the new root stays bifurcating.
        """
        if self.root is None:
            return
        dist0, _ = self._weighted_distances(self.root)
        a = max(dist0, key=lambda n: dist0[n])
        dist_a, pred_a = self._weighted_distances(a)
        b = max(dist_a, key=lambda n: dist_a[n])
        diameter = dist_a[b]
        if diameter <= 0:
            return

        # Reconstruct the path from a to b and locate the edge crossing the
        # midpoint (diameter / 2).
        path = []
        cur = b
        while cur is not None:
            path.append(cur)
            cur = pred_a[cur]
        path.reverse()  # a ... b

        cum = 0.0
        mid = diameter / 2.0
        for i in range(len(path) - 1):
            u = path[i]          # the end of this edge closer to tip `a`
            v = path[i + 1]      # the end closer to tip `b`
            if v.parent is u:
                # The edge length is stored on the child v; rerooting "on the
                # branch above v" is the edge (u, v).
                w = v.branch_length if v.branch_length is not None else 0.0
                child = v
                toward_b = True
            else:
                w = u.branch_length if u.branch_length is not None else 0.0
                child = u
                toward_b = False
            edge_start = cum
            cum += w
            if mid > cum + 1e-12:
                continue  # the midpoint lies farther along the path

            # Fraction of THIS edge at which the midpoint sits, measured from
            # u towards v. Splitting the edge at its own midpoint (frac=0.5)
            # would only be correct when the tree midpoint happens to fall in
            # the middle of the edge — the general answer is below.
            t = 0.0 if w <= 0 else (mid - edge_start) / w
            t = max(0.0, min(1.0, t))
            # reroot(child, frac) gives `child` the fraction frac of the edge
            # and the other end point the remaining 1-frac. `child` is at the
            # b-end of the edge when toward_b, so the distance from `a` to the
            # new root is edge_start + w*(1-frac) there, and edge_start +
            # w*frac when `child` is at the a-end.
            frac = (1.0 - t) if toward_b else t
            # Rooting always lands ON the edge (never on an existing node), so
            # the new root stays bifurcating instead of a basal polytomy.
            self.reroot(child, frac=frac)
            return
        # diameter <= 0 already returned earlier; this is a safety net.
        return

    def __repr__(self):
        return "<Tree %s taxa=%d>" % (self.name or "untitled", self.n_taxa)
