from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from tsumtsum_analyze.publish import default_analyzer_dirs, publish_bundle


def main() -> None:
    data, assets = default_analyzer_dirs()
    counts = publish_bundle(data, assets)
    print(f"解析アプリへ書き出しました: {data}")
    print(counts)


if __name__ == "__main__":
    main()
