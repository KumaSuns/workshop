from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.volume import mute_playback


def main() -> None:
    mute_playback()
    app = QApplication(sys.argv)
    app.setApplicationName("画面ミラー")
    app.setOrganizationName("workshop")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
