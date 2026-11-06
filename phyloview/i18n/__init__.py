"""Internationalisation (i18n): English / Chinese bilingual UI support."""

from PySide6.QtCore import QObject, Signal

EN = "en"
ZH = "zh_CN"

# Source-string (English) -> translation dictionary.
_TRANSLATIONS = {
    ZH: {
        # menu bar
        "File": "文件",
        "Import tree file...": "导入树文件",
        "Export": "导出",
        "Export as PNG...": "导出为 PNG...",
        "Export as JPEG...": "导出为 JPEG...",
        "Export as SVG...": "导出为 SVG...",
        "Export as PDF...": "导出为 PDF...",
        "Export as Newick...": "导出为 Newick...",
        "Export labels...": "导出标签...",
        # settings (2.1)
        "Save settings...": "保存设置...",
        "Load settings...": "加载设置...",
        "Save Settings": "保存设置",
        "Load Settings": "打开设置文件",
        "Settings files (*.json);;All files (*.*)":
            "设置文件 (*.json);;所有文件 (*.*)",
        "Settings saved": "设置已保存",
        "Settings loaded": "设置已加载",
        "Failed to save settings:": "保存设置失败：",
        "Failed to load settings:": "加载设置失败：",
        "Exit": "退出",
        "Edit": "编辑",
        "View": "视图",
        "Zoom In": "放大",
        "Zoom Out": "缩小",
        "Fit to Window": "适应窗口",
        "Tree": "树",
        "Layout": "布局",
        "Rectangular": "矩形",
        "Cladogram": "分支图",
        "Radial": "放射状",
        "Language": "语言",
        "English": "English",
        "中文": "中文",
        "Help": "帮助",
        "About": "关于",
        "Style": "样式",
        # dialogs / messages
        "Open Tree File": "打开树文件",
        "Tree files (*.nwk *.tre *.treefile *.contree *.newick *.nex *.nexus *.nxs *.phy);;All files (*.*)":
            "树文件 (*.nwk *.tre *.treefile *.contree *.newick *.nex *.nexus *.nxs *.phy);;所有文件 (*.*)",
        "Error": "错误",
        "Failed to load tree:": "加载树失败：",
        "Export Tree": "导出树",
        "Image files (*.png *.jpg);;SVG files (*.svg);;PDF files (*.pdf)":
            "图片文件 (*.png *.jpg);;SVG 文件 (*.svg);;PDF 文件 (*.pdf)",
        "Newick files (*.nwk *.tre *.newick);;All files (*.*)":
            "Newick 文件 (*.nwk *.tre *.newick);;所有文件 (*.*)",
        # label export (1.9)
        "Export Labels": "导出标签",
        "Text files (*.txt);;CSV files (*.csv);;Excel workbooks (*.xlsx)":
            "文本文件 (*.txt);;CSV 文件 (*.csv);;Excel 工作簿 (*.xlsx)",
        "Original label": "原始标签",
        "Displayed label": "显示标签",
        "Labels exported": "标签已导出",
        "tips": "个末端",
        "No tree loaded": "尚未加载树",
        "Please open a tree file first.": "请先打开一个树文件。",
        "Export failed:": "导出失败：",
        "Drop a tree file here to open it": "将树文件拖拽到此处打开",
        "drag a Newick/Nexus file here": "将 Newick/Nexus 文件拖拽到此处",
        # style panel
        "Tree Layout": "树布局",
        "Branch": "分支",
        "Color": "颜色",
        "Line Width": "线宽",
        "Show branch lengths": "显示枝长",
        "Show scale bar": "显示比例尺",
        # scale bar controls (1.9)
        "Scale bar length": "比例尺长度",
        "Horizontal offset": "水平偏移",
        "Vertical offset": "垂直偏移",
        "Reset position": "复位位置",
        "Scale bar position": "比例尺位置",
        "Auto": "自动",
        "Length of the scale bar, in the same units as the "
        "branch lengths (0 = automatic)":
            "比例尺代表的枝长大小（单位与枝长相同，0 = 自动）",
        "Horizontal offset from the default position":
            "相对默认位置的水平偏移（像素）",
        "Vertical offset from the default position":
            "相对默认位置的垂直偏移（像素）",
        "Put the scale bar back at the bottom centre":
            "把比例尺放回底部居中位置",
        "Drag the scale bar on the canvas, or set the offsets above":
            "可直接在树上拖动比例尺，也可在上方输入偏移量",
        "Drag the scale bar on the canvas to position it":
            "可直接在树上拖动比例尺调整位置",
        "Nodes": "节点",
        "Node markers": "节点标记",
        "Show markers": "显示节点标记",
        "Shape": "形状",
        "Size": "大小",
        "circle": "圆形",
        "square": "方形",
        "triangle": "三角形",
        "Support Values": "支持率",
        "Show support": "显示支持率",
        "Decimals": "小数位",
        # multiple support metrics (1.8) — QuartetScores / IQ-TREE
        "Values to display": "显示指标",
        "Show metric names": "显示指标名称",
        "Choose which support values are drawn on the tree (multiple values "
        "are joined with /)":
            "勾选要在树上显示的支持率指标（多个指标之间用 / 连接）",
        "Show the metric name in front of every value":
            "在每个数值前显示指标名称（便于同时显示多个指标时区分）",
        "Original tree support": "原始树支持率",
        "QP-IC": "QP-IC",
        "LQ-IC": "LQ-IC",
        "EQP-IC": "EQP-IC",
        "Support 1 (before /)": "支持率 1（斜杠前）",
        "Support 2 (after /)": "支持率 2（斜杠后）",
        "Support 3": "支持率 3",
        "Support 4": "支持率 4",
        "Support 5": "支持率 5",
        "Support 6": "支持率 6",
        "Hide values below threshold": "隐藏低于阈值的支持率",
        "Per-metric threshold": "各指标阈值",
        "Threshold": "阈值",
        "Multiple support metrics detected — choose them in Support Values":
            "检测到多个支持率指标 — 可在「支持率」中勾选显示",
        "Labels": "标签",
        "Show labels": "显示标签",
        "Font Size": "字号",
        "Horizontal stretch": "横向拉伸",
        "Vertical stretch": "纵向拉伸",
        "Tree Operations": "树操作",
        "Root": "置根",
        "Root the tree on the branch above the selected clade: click a "
        "branch/node on the tree, then press here. The selected clade stays "
        "one intact clade and becomes the basal lineage.":
            "在选中支系基部的枝条上定根：先在树上点选一个分支或节点，"
            "再点击此按钮。该支系会完整保留为一个支系，并成为树的基部分支。",
        "Midpoint root": "中点置根",
        "Find the root at the midpoint of the longest path":
            "在最长路径的中点处定根",
        "Branch order": "分支排序",
        "Default": "默认",
        "Ascending": "升序",
        "Descending": "降序",
        "Branch ordering — sort clades ascending or descending by clade size":
            "分支排序——按支系大小（末端类群数）升序或降序排列各支系",
        "Root length": "根枝长",
        "Length of the stem drawn to the left of the root, in the same units "
        "as the branch lengths":
            "根左侧引出的根枝长度（单位与枝长一致）",
        "Select a branch/node first": "请先选中一个分支或节点",
        # rotation / collapse (1.4)
        "Flip": "翻转",
        "Flip — flip individual nodes or entire subtrees":
            "翻转——反转单个节点或整个子树（交换其下各子支系的上下顺序）",
        "Collapse": "折叠",
        "Collapse / expand — collapse clades to triangles with configurable "
        "height and labels":
            "折叠/展开——将支系折叠为三角形，高度与标签均可设置",
        "Expand": "展开",
        "Expand the selected collapsed clade": "展开选中的折叠支系",
        "Expand all": "全部展开",
        "Expand every collapsed clade": "展开所有折叠支系",
        "Collapse height": "折叠高度",
        "Height of the triangle drawn for a collapsed clade, in units of the "
        "tip-to-tip spacing (0 = automatic, i.e. the span of the tips it "
        "replaces)":
            "折叠三角形的高度，以末端之间的间距为单位"
            "（0 = 自动，即沿用被折叠末端的跨度）",
        "Collapse label": "折叠标签",
        "Label drawn next to a collapsed clade's triangle":
            "折叠支系三角形旁边显示的标签",
        "Select a branching node first": "请先选中一个分叉节点",
        # label annotations (1.5) — tip labels from a spreadsheet
        "Label annotations": "标签注释",
        "Import label annotations...": "导入标签注释...",
        "Import Label Table": "导入标签表格",
        "Import table...": "导入表格...",
        "Reload table": "刷新表格",
        "Clear table": "清除表格",
        "Re-read the table from disk and refresh the labels":
            "重新读取表格并刷新树上的标签",
        "Forget the table and restore the original labels":
            "清除表格，恢复原始标签",
        "Auto sync": "自动同步",
        "Watch the table file and refresh the labels when it changes":
            "监听表格文件，文件改动时自动刷新标签",
        "First row is header": "首行为表头",
        "The first row of the sheet holds the column titles instead of data":
            "表格第一行为列名，而不是数据",
        "Sheet": "工作表",
        "Separator": "分隔符",
        "Separator inserted between the selected columns":
            "多个显示列之间的分隔符（默认：一个空格）",
        "Current separator: %s": "当前分隔符：%s",
        "Columns to show on the tree (the first column matches the tip labels)":
            "在树上显示的列（第一列用于匹配末端标签）",
        "No table loaded": "未导入表格",
        "%d of %d tip labels matched": "末端标签已匹配 %d/%d",
        "%d unmatched - check column A or the header option":
            "%d 个未匹配 — 检查 A 列或「首行为表头」",
        "Failed to load table:": "加载表格失败：",
        "Labels updated from %s": "已根据 %s 更新标签",
        "Label table cleared": "已清除标签表格",
        "Spreadsheet files (*.xlsx *.xlsm *.csv *.tsv *.txt);;All files (*.*)":
            "表格文件 (*.xlsx *.xlsm *.csv *.tsv *.txt);;所有文件 (*.*)",
        "Drop a tree file or a label table here":
            "将树文件或标签表格拖拽到此处",
        # label formatting (1.6) — bold / italic / colour from the sheet
        "Sync table format": "同步表格格式",
        "Use the spreadsheet's bold, italic and colour for the tip labels "
        "(the font size stays under PhyloClear's control)":
            "采用表格中的加粗、斜体与颜色绘制末端标签（字号仍由本软件控制）",
        "Table formatting applied": "已应用表格格式",
        "Table formatting ignored": "已忽略表格格式",
        "Apply to": "应用到",
        "Whole tree": "整棵树",
        "Selected subtree": "选中子树",
        "Apply": "应用",
        "Selected Node": "选中节点",
        "Name": "名称",
        "Support": "支持率",
        "Branch length": "枝长",
        "Annotation": "标注",
        "Set color": "设置颜色",
        "Pick color": "选择颜色",
        "Save": "保存",
        "No selection": "未选中",
        "Click a branch or node to select it": "点击分支或节点进行选择",
        "Selected": "已选中",
        # about
        "Interactive phylogenetic tree viewer and editor": "交互式系统发育树查看与编辑器",
        "A from-scratch Python reimplementation of FigTree.": "基于 FigTree 功能、用 Python 从零重新实现的软件。",
        "Licensed under GPL-3.0-or-later.": "依据 GPL-3.0-or-later 许可证发布。",
        "OK": "确定",
        "About PhyloClear": "关于 PhyloClear",
        "Open": "打开",
        "Cancel": "取消",
        "Reset": "重置",
        # colour dialog (0.01): Qt's non-native QColorDialog builds these
        # labels in C++; they never pass through Translator on their own.
        "Select Color": "选择颜色",
        "&Basic colors": "基本颜色",
        "&Custom colors": "自定义颜色",
        "Hu&e:": "色相：",
        "&Sat:": "饱和度：",
        "&Val:": "明度：",
        "&Red:": "红色：",
        "&Green:": "绿色：",
        "Bl&ue:": "蓝色：",
        "A&lpha channel:": "透明度：",
        "&HTML:": "HTML：",
        "&Pick Screen Color": "拾取屏幕颜色",
        "&Add to Custom Colors": "添加到自定义颜色",
        # project / settings files (0.01)
        "Open Tree or Settings": "打开树文件或设置文件",
        "Tree files (*.nwk *.tre *.newick *.nex *.nexus *.nxs *.phy);;"
        "Settings files (*.phcproj *.json);;All files (*.*)":
            "树文件 (*.nwk *.tre *.newick *.nex *.nexus *.nxs *.phy);;"
            "设置文件 (*.phcproj *.json);;所有文件 (*.*)",
        "Settings files (*.phcproj *.json);;All files (*.*)":
            "设置文件 (*.phcproj *.json);;所有文件 (*.*)",
        "Tree file not found:": "工程文件引用的树文件不存在：",
        "Settings file is not a PhyloClear project":
            "该文件不是 PhyloClear 设置文件",
        "Project saved": "设置已保存",
        "Project loaded": "设置已加载",
    }
}


class Translator(QObject):
    """Holds the current language and translates source strings."""

    languageChanged = Signal(str)

    def __init__(self, language=ZH):
        super().__init__()
        self.language = language

    def tr(self, source):
        if self.language == ZH:
            return _TRANSLATIONS.get(ZH, {}).get(source, source)
        return source

    def set_language(self, language):
        if language not in (EN, ZH):
            language = EN
        if language != self.language:
            self.language = language
            self.languageChanged.emit(language)


# A module-level convenience instance.
_default = Translator()


def tr(source):
    return _default.tr(source)
