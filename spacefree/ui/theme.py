from PyQt6.QtGui import QColor

from ..models import BAD, GOOD, IMPORTANT, REVIEW

LABEL_COLORS = {
    BAD: QColor("#e5534b"),
    REVIEW: QColor("#d29922"),
    GOOD: QColor("#3fb950"),
    IMPORTANT: QColor("#58a6ff"),
}

STYLE = """
QWidget { background: #0d1117; color: #e6edf3; font-size: 13px; }
QMainWindow, QTabWidget::pane { border: 0; }
QTabBar::tab { background: #161b22; padding: 8px 18px; border: 0; margin-right: 2px; }
QTabBar::tab:selected { background: #21262d; border-bottom: 2px solid #58a6ff; }
QPushButton { background: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #30363d; }
QPushButton:disabled { color: #6e7681; }
QPushButton#primary { background: #238636; border-color: #2ea043; font-weight: bold; }
QPushButton#primary:hover { background: #2ea043; }
QPushButton#danger { background: #b62324; border-color: #da3633; font-weight: bold; }
QPushButton#danger:hover { background: #da3633; }
QTableWidget, QTreeWidget, QListWidget, QLineEdit, QComboBox, QTextEdit {
    background: #0d1117; border: 1px solid #30363d; border-radius: 4px; gridline-color: #21262d;
    selection-background-color: #1f6feb; alternate-background-color: #11161d; }
QHeaderView::section { background: #161b22; border: 0; padding: 6px; font-weight: bold; }
QProgressBar { background: #21262d; border: 0; border-radius: 4px; text-align: center; height: 14px; }
QProgressBar::chunk { background: #58a6ff; border-radius: 4px; }
QGroupBox { border: 1px solid #30363d; border-radius: 6px; margin-top: 12px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #8b949e; }
QLabel#muted { color: #8b949e; }
QLabel#big { font-size: 26px; font-weight: bold; }
"""

VERDICT_COLORS = {
    "Delete": QColor("#e5534b"),
    "Review": QColor("#d29922"),
    "Keep": QColor("#3fb950"),
    "Educational": QColor("#58a6ff"),
}
