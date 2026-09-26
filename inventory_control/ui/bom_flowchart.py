"""Scrollable, zoomable flowchart for a nested bill of materials."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from inventory_control.models import BOMTreeNode


CRITICAL_BUILD_LIMIT = 100
LOW_BUILD_LIMIT = 500


def capacity_level(buildable: int) -> str:
    if buildable <= CRITICAL_BUILD_LIMIT:
        return "critical"
    if buildable <= LOW_BUILD_LIMIT:
        return "low"
    return "ready"


class BOMFlowchart(QGraphicsView):
    NODE_WIDTH = 238
    NODE_HEIGHT = 118
    COLUMN_GAP = 105
    ROW_GAP = 24
    MARGIN = 34

    COLORS = {
        "critical": ("#f16e75", "#51272d", "#e36a72"),
        "low": ("#f6c85f", "#4c3e23", "#d4aa45"),
        "ready": ("#80b5f6", "#243447", "#6389ae"),
    }

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("BOMFlowchart")
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMinimumHeight(390)
        self.setBackgroundBrush(QBrush(QColor("#171b20")))
        self.setFrameShape(QGraphicsView.NoFrame)
        self._node_count = 0

    def clear_bom(self) -> None:
        self.scene().clear()
        self._node_count = 0

    def set_bom(self, root: BOMTreeNode, capacities: dict[str, int]) -> None:
        self.clear_bom()
        positions: dict[int, tuple[float, float]] = {}
        next_row = [self.MARGIN]

        def layout(node: BOMTreeNode, depth: int) -> float:
            x = self.MARGIN + depth * (self.NODE_WIDTH + self.COLUMN_GAP)
            if node.children:
                child_centers = [layout(child, depth + 1) for child in node.children]
                center = (child_centers[0] + child_centers[-1]) / 2
            else:
                center = next_row[0] + self.NODE_HEIGHT / 2
                next_row[0] += self.NODE_HEIGHT + self.ROW_GAP
            positions[id(node)] = (x, center - self.NODE_HEIGHT / 2)
            return center

        layout(root, 0)
        subtree_capacity: dict[int, int] = {}

        def calculate(node: BOMTreeNode) -> int:
            if node.children:
                value = min(calculate(child) for child in node.children)
            else:
                value = capacities[node.part_number]
            subtree_capacity[id(node)] = value
            return value

        calculate(root)

        def render(node: BOMTreeNode) -> None:
            x, y = positions[id(node)]
            for child in node.children:
                child_x, child_y = positions[id(child)]
                start = QPointF(x + self.NODE_WIDTH, y + self.NODE_HEIGHT / 2)
                end = QPointF(child_x, child_y + self.NODE_HEIGHT / 2)
                path = QPainterPath(start)
                bend = (start.x() + end.x()) / 2
                path.cubicTo(QPointF(bend, start.y()), QPointF(bend, end.y()), end)
                level = capacity_level(subtree_capacity[id(child)])
                self.scene().addPath(path, QPen(QColor(self.COLORS[level][2]), 2))
                self._text(f"×{child.quantity_per_parent}",
                           x + self.NODE_WIDTH + 12, child_y + self.NODE_HEIGHT / 2 - 28,
                           80, 10, "#abb6c5", bold=True)
                render(child)
            self._card(node, x, y, subtree_capacity[id(node)])

        render(root)
        bounds = self.scene().itemsBoundingRect().adjusted(-self.MARGIN, -self.MARGIN,
                                                            self.MARGIN, self.MARGIN)
        self.scene().setSceneRect(bounds)
        self.resetTransform()
        self._fit_initial_zoom()

    def _card(self, node: BOMTreeNode, x: float, y: float, buildable: int) -> None:
        level = capacity_level(buildable)
        accent, fill, border = self.COLORS[level]
        rect = QRectF(x, y, self.NODE_WIDTH, self.NODE_HEIGHT)
        outline = QPainterPath()
        outline.addRoundedRect(rect, 10, 10)
        self.scene().addPath(outline, QPen(QColor(border), 1.5), QBrush(QColor(fill)))
        self.scene().addRect(QRectF(x, y + 13, 4, self.NODE_HEIGHT - 26),
                             QPen(Qt.NoPen), QBrush(QColor(accent)))
        kind = "ASSEMBLY" if node.children else "MATERIAL"
        self._text(kind, x + 16, y + 10, 200, 9, accent, bold=True)
        self._text(node.part_number, x + 16, y + 30, 210, 13, "#f4f6f9", bold=True)
        description_font = QFont("Segoe UI", 10)
        short_description = QFontMetrics(description_font).elidedText(
            node.description, Qt.ElideRight, 202
        )
        description = self._text(short_description, x + 16, y + 54, 208, 10, "#c2cbd6")
        description.setToolTip(node.description)
        self._text(f"{buildable:,} final builds", x + 16, y + 82, 208, 11, accent, bold=True)
        self._node_count += 1

    def _text(self, value: str, x: float, y: float, width: float, size: int,
              color: str, *, bold: bool = False):
        item = self.scene().addText(value)
        item.setDefaultTextColor(QColor(color))
        font = QFont("Segoe UI", size)
        font.setBold(bold)
        item.setFont(font)
        item.setTextWidth(width)
        item.setPos(x, y)
        return item

    def _fit_initial_zoom(self) -> None:
        if not self._node_count:
            return
        width = max(self.viewport().width() - 16, 1)
        scale = min(1.0, max(0.65, width / self.sceneRect().width()))
        self.scale(scale, scale)

    def zoom_in(self) -> None:
        self._zoom(1.2)

    def zoom_out(self) -> None:
        self._zoom(1 / 1.2)

    def fit_chart(self) -> None:
        if self._node_count:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def _zoom(self, factor: float) -> None:
        current = self.transform().m11()
        if 0.25 <= current * factor <= 2.5:
            self.scale(factor, factor)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            self._zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
            event.accept()
        else:
            super().wheelEvent(event)
