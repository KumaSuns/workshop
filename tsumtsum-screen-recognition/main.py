from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def _initial_paths(argv: list[str]) -> list[str]:
    if "--import-json" in argv:
        index = argv.index("--import-json")
        if index + 1 < len(argv):
            payload = json.loads(Path(argv[index + 1]).read_text(encoding="utf-8"))
            return [str(path) for path in payload.get("paths", [])]
    return [arg for arg in argv[1:] if not arg.startswith("-") and Path(arg).exists()]


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("TsumTsum Screen Trainer")
    app.setOrganizationName("workshop")
    window = MainWindow()
    window.show()
    paths = _initial_paths(sys.argv)
    if paths:
        QTimer.singleShot(0, lambda: window.import_incoming_paths(paths))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
