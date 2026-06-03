from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen


class OCRPreviewOverlay(QWidget):
    """
    Reusable OCR preview overlay component.
    Shows a fullscreen semi-transparent mask with a cutout for the OCR area.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Set window attributes: transparent background, mouse transparency
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # Set window flags: topmost, frameless, tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        self.area_rect = None
        
        # Default to primary screen geometry
        self.update_geometry()

    def update_geometry(self):
        """Update overlay to cover the primary screen."""
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

    def show_preview(self, area: dict):
        """
        Show overlay with red rectangle at area coordinates.
        
        Args:
            area: dict with keys {x, y, width, height} or None
        """
        if area and all(k in area for k in ('x', 'y', 'width', 'height')):
            # 预览层使用 Qt 逻辑坐标，OCR 区域配置是物理像素坐标。
            # 仅在“预览”中做 DPI 缩放换算（除以缩放比），不影响真实截图区域设置逻辑。
            screen = QApplication.primaryScreen()
            scale = float(screen.devicePixelRatio()) if screen else 1.0
            if scale <= 0:
                scale = 1.0

            x = int(round(float(area['x']) / scale))
            y = int(round(float(area['y']) / scale))
            width = max(1, int(round(float(area['width']) / scale)))
            height = max(1, int(round(float(area['height']) / scale)))

            self.area_rect = QRect(x, y, width, height)
        else:
            self.area_rect = None
            
        self.update_geometry()
        self.show()
        self.raise_()
        self.update()  # Trigger repaint

    def hide_preview(self):
        """Hide overlay immediately."""
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Create overlay path covering full screen
        overlay_path = QPainterPath()
        overlay_path.addRect(QRectF(self.rect()))
        
        # Subtract area rect if valid to create "cutout"
        if self.area_rect and not self.area_rect.isNull():
            selection_path = QPainterPath()
            selection_path.addRect(QRectF(self.area_rect))
            overlay_path -= selection_path
        
        # Fill mask with semi-transparent black
        painter.fillPath(overlay_path, QColor(0, 0, 0, 120))
        
        # Draw red rectangle border
        if self.area_rect and not self.area_rect.isNull():
            pen = QPen(QColor("#FF0000"), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.area_rect)
