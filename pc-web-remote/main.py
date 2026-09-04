from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.paths import APP_ROOT


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PC Remote")
    app.setOrganizationName("workshop")
    icon = APP_ROOT / "app.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
