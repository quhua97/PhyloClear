"""Rendering configuration and default styles."""

from .layout import ALL_MODES, RECTANGULAR, RADIAL, CLADOGRAM  # re-export

__all__ = ["TreeStyle", "ALL_MODES", "RECTANGULAR", "RADIAL", "CLADOGRAM"]


class TreeStyle:
    """Global visual style for a tree rendering."""

    def __init__(self):
        # layout (default: rectangular phylogram, matching FigTree's default)
        self.layout_mode = RECTANGULAR
        # independent stretch of the tree: horizontal scales branch lengths,
        # vertical scales leaf spacing. 1.0 = no stretch.
        self.horizontal_stretch = 1.0
        self.vertical_stretch = 1.0
        # Length of the stem drawn to the left of the root, in the same units
        # as the branch lengths. 0.0 = no stem (FigTree's default).
        self.root_length = 0.0
        # Branch ordering: "default" | "ascending" | "descending" by clade size.
        self.branch_order = "default"
        # Collapsed clades are drawn as triangles. collapse_height is their
        # vertical height in units of the tip-to-tip spacing; 0.0 = automatic
        # (the clade keeps the vertical span of the tips it replaces).
        self.collapse_height = 0.0
        self.collapse_fill_color = "#cccccc"

        # branches (thin black lines, like FigTree's publication style)
        self.branch_color = "#000000"
        self.branch_width = 1.0
        # FigTree does not print per-branch length numbers by default; the
        # scale bar conveys the length instead. (User can re-enable in panel.)
        self.show_branch_lengths = False
        self.branch_length_font_size = 8.0
        self.branch_length_color = "#000000"
        self.show_scale_bar = True
        # 1.9: the scale bar can be given an exact length (branch-length
        # units). 0.0 = old behaviour: pick a nice round number automatically.
        self.scale_bar_length = 0.0
        # Offset from the automatic bottom-centre position, in scene pixels.
        # Kept in the style so dragging survives every later rebuild/export.
        self.scale_bar_offset_x = 0.0
        self.scale_bar_offset_y = 0.0

        # support values (hidden by default, matching FigTree)
        self.show_support = False
        self.support_font_size = 8.0
        # 1.9: publication figures use black support values, not red.
        self.support_color = "#000000"
        # Where a support value sits relative to its branching point.
        # "above_branch" = above the incoming horizontal branch, ending just
        # before the branching point (FigTree-style, requested by the user).
        # "below_node" is the pre-1.9 behaviour, kept as a fallback.
        self.support_position = "above_branch"
        # 1.8: QuartetScores IC scores carry six decimals, so keep enough
        # precision by default. Trailing zeroes are stripped when formatting,
        # so "100" still reads "100" and "99.3" still reads "99.3".
        self.support_decimals = 6
        # Which of the tree's support metrics to draw. None = not configured
        # (fall back to the raw node label); [] = the user unchecked them all.
        self.support_fields = None
        # Prefix each value with a short metric name (useful when several IC
        # scores are shown together).
        self.support_show_names = False
        # 0.01: hide support values that fall below a per-metric threshold.
        # When enabled, every metric whose numeric value is below
        # ``support_hide_thresholds[key]`` is dropped from the on-screen label
        # (a value that is not a number is always kept). An empty dict means
        # "no threshold set for this metric" — that metric is then never hidden.
        self.support_hide_below_enabled = False
        self.support_hide_thresholds = {}

        # nodes / markers (no node circles by default)
        self.show_node_markers = False
        self.node_shape = "circle"  # circle | square | triangle
        self.node_size = 5.0
        self.node_color = "#333333"
        self.node_outline = "#111111"

        # leaf labels (small black sans-serif, like FigTree)
        self.show_leaf_labels = True
        self.label_font_family = "Sans Serif"
        self.label_font_size = 9.0
        self.label_color = "#000000"
        self.label_italic = False
        self.label_bold = False

        # canvas
        self.background_color = "#ffffff"

    def branch_color_for(self, node):
        """Resolve branch color with per-node override."""
        return node.style.get("color", self.branch_color)

    def branch_width_for(self, node):
        return node.style.get("width", self.branch_width)

    def label_color_for(self, node):
        return node.style.get("label_color", self.label_color)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    def update(self, **kwargs):
        self.__dict__.update(kwargs)
