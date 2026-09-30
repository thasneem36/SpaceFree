import sys
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox

from spacefree.ui.main_window import MainWindow
from spacefree.ui.theme import STYLE


def _excepthook(exc_type, exc, tb) -> None:
    # PyQt6 aborts the process on unhandled slot exceptions; show them instead.
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.stderr.write(text)
    try:
        QMessageBox.critical(None, "SpaceFree error", text[-1500:])
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
