import sys

from PyQt6.QtWidgets import QApplication

from spacefree.ui.main_window import MainWindow
from spacefree.ui.theme import STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
