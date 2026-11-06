"""Tree layout engines: rectangular (phylogram), cladogram and radial."""

import math

RECTANGULAR = "rectangular"
CLADOGRAM = "cladogram"
RADIAL = "radial"

ALL_MODES = (RECTANGULAR, CLADOGRAM, RADIAL)


class TreeLayout:
    """Compute 2-D coordinates for every node of a tree.

    Coordinates are stored directly on each node as ``node.x`` / ``node.y``.
    For rectangular/cladogram: x is horizontal (distance from root), y is
    vertical (leaf index). For radial: x/y are Cartesian coordinates on a
    unit-ish circle with the root at the origin.
    """

    def __init__(self, tree, mode=RECTANGULAR, collapse_height=0.0):
        self.tree = tree
        self.mode = mode
        # Height of a collapsed clade's triangle, expressed in leaf-spacing
        # units (1.0 = the gap between two adjacent tips). 0.0 = automatic:
        # the clade keeps the vertical span of the tips it replaces.
        self.collapse_height = collapse_height or 0.0
        self.width = 0.0
        self.height = 0.0
        self.min_x = self.max_x = 0.0
        self.min_y = self.max_y = 0.0
        # Nodes that are actually drawn: everything except the descendants of
        # collapsed clades (the collapsed node itself IS drawn, as a triangle).
        self.visible = None

    def compute(self):
        if self.tree.root is None:
            return
        self._mark_visibility()
        self._assign_y()
        # If the tree carries no branch lengths at all, fall back to unit
        # branch lengths so the terminal branches remain visible (a proper
        # cladogram) instead of collapsing to a single vertical line.
        has_lengths = self._has_branch_lengths()
        if self.mode == RADIAL:
            self._compute_radial(unit=not has_lengths)
        elif self.mode == CLADOGRAM:
            self._compute_depth(unit=True, align_tips=True)
        else:
            self._compute_depth(unit=not has_lengths)
        self._compute_bbox()

    # -- visibility / collapse --------------------------------------------
    def _mark_visibility(self):
        """Collect the nodes that survive collapse.

        A collapsed clade is drawn as a triangle, so the collapsed node itself
        stays visible while all of its descendants become invisible.
        """
        self.visible = set()

        def rec(node):
            self.visible.add(node)
            if node.collapsed and not node.is_leaf:
                return  # descendants are represented by the triangle
            for child in node.children:
                rec(child)

        rec(self.tree.root)

    def is_visible(self, node):
        return True if self.visible is None else node in self.visible

    def rows_for(self, node):
        """How many leaf rows a terminal occupies in the drawing.

        A plain tip takes one row. A collapsed clade takes as many rows as it
        has tips (automatic height), or the user's fixed ``collapse_height``
        when that is set (still in units of the tip-to-tip spacing).
        """
        if node.collapsed and not node.is_leaf:
            rows = self.collapse_height if self.collapse_height > 0 else node.n_leaves
            try:
                return max(1.0, float(math.ceil(rows - 1e-9)))
            except (TypeError, ValueError):
                return 1.0
        return 1.0

    def row_count(self):
        """Total number of leaf rows used by the drawing."""
        return sum(self.rows_for(t) for t in self._terminals())

    def _terminals(self):
        """Terminal units of the drawing: visible tips and collapsed clades."""
        out = []

        def rec(node):
            if node.is_leaf or (node.collapsed and not node.is_leaf):
                out.append(node)
                return
            for child in node.children:
                rec(child)

        if self.tree.root is not None:
            rec(self.tree.root)
        return out

    # -- helpers -----------------------------------------------------------
    def _has_branch_lengths(self):
        for node in self.tree.nodes:
            if node.is_root:
                continue
            if node.branch_length is not None:
                return True
        return False

    def _leaves(self):
        # Traverse from the root instead of using ``tree.nodes`` so the leaf
        # order always matches the *current* child order (``tree.nodes`` is a
        # cached postorder list that would be stale after branch ordering).
        # Since 1.4 a collapsed clade counts as one terminal unit: everything
        # below it is replaced by its triangle.
        return self._terminals()

    def _assign_y(self):
        """Assign rows to terminal units; internal nodes take their children's mean.

        Collapsed clades may occupy more than one row (see :meth:`rows_for`),
        so rows are counted cumulatively instead of using the terminal index.
        """
        terminals = self._terminals()
        row = 0.0
        for terminal in terminals:
            rows = self.rows_for(terminal)
            terminal.y = row + (rows - 1.0) / 2.0
            row += rows

        def rec(node):
            if node.is_leaf or (node.collapsed and not node.is_leaf):
                return node.y
            ys = [rec(child) for child in node.children]
            node.y = sum(ys) / len(ys)
            return node.y

        rec(self.tree.root)

    def _compute_depth(self, unit, align_tips=False):
        def rec(node, dist):
            node.x = dist
            for child in node.children:
                if unit:
                    bl = 1.0
                else:
                    bl = child.branch_length if child.branch_length else 0.0
                rec(child, dist + bl)

        rec(self.tree.root, 0.0)
        if align_tips:
            # Standard cladogram: pin every tip to the right edge so all taxa
            # are aligned, regardless of the tree's balance. Hidden tips (those
            # inside a collapsed clade) are pinned too, otherwise the collapsed
            # triangle would stop short of the tip line.
            all_leaves = list(self.tree.root.iter_leaves())
            max_x = max((n.x for n in all_leaves), default=0.0)
            for leaf in all_leaves:
                leaf.x = max_x

    def _compute_radial(self, unit=False):
        terminals = self._terminals()
        tip_ids = set(id(t) for t in terminals)
        n = len(terminals)
        # Divide by n (not n-1) so the first and last leaves do not collapse
        # onto the same angle; leaves span 2*pi*(n-1)/n, leaving a gap.
        n_ang = float(max(n, 1))

        def rec(node, dist):
            node._dist = dist
            for child in node.children:
                if unit:
                    bl = 1.0
                else:
                    bl = child.branch_length if child.branch_length else 0.0
                rec(child, dist + bl)

        rec(self.tree.root, 0.0)
        max_dist = max((leaf._dist for leaf in terminals), default=0.0) or 1.0

        for node in self.tree.nodes:
            if self.visible is not None and node not in self.visible:
                continue
            theta = (node.y / n_ang) * (2.0 * math.pi) - math.pi / 2.0
            # Terminal units (tips and collapsed clades) are pinned to the
            # outer circle; internal nodes sit at a radius proportional to
            # their depth (standard circular phylogram).
            if node.is_leaf or (id(node) in tip_ids and node.parent is not None):
                radius = 1.0
            else:
                radius = node._dist / max_dist
            node.x = radius * math.cos(theta)
            node.y = radius * math.sin(theta)

    def _compute_bbox(self):
        # Only visible nodes: collapsed clades hide their descendants, whose
        # (stale) coordinates must not enlarge the drawing.
        nodes = [n for n in self.tree.nodes
                 if self.visible is None or n in self.visible]
        if not nodes:
            nodes = list(self.tree.nodes)
        xs = []
        ys = []
        for node in nodes:
            xs.append(node.x)
            ys.append(node.y)
            if node.collapsed and node.children and self.mode != RADIAL:
                # The triangle reaches beyond the collapsed node itself: down
                # to the deepest tip it hides, and half its height to either
                # side of the node's y. Without this the scale bar (placed
                # just below layout.height) would be drawn across the triangle.
                xs.append(max(sub.x for sub in node.iter_nodes()))
                half = self.rows_for(node) / 2.0
                ys.append(node.y - half)
                ys.append(node.y + half)
        self.min_x, self.max_x = min(xs), max(xs)
        self.min_y, self.max_y = min(ys), max(ys)
        self.width = max(self.max_x - self.min_x, 1e-6)
        self.height = max(self.max_y - self.min_y, 1e-6)
