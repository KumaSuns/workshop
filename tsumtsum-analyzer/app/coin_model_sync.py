"""サーバーのコイン用モデルと手元のファイルを比べ、押したときだけ取り直す。"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal

from app.paths import WORKSHOP_ROOT

MODELS_API = "http://hokkai-syabusyabu.com/home_page/workshop/models/api.php"
COIN_MODEL_NAMES = (
    "coin.pt",
    "coin_digits.pt",
    "result_coin.pt",
    "result_coin_digits.pt",
)
_MODELS_DIR = WORKSHOP_ROOT / "tsumtsum-screen-recognition" / "data" / "models"


def _token() -> str:
    stored = str(QSettings("workshop", "WorkshopDataServer").value("api_token", "") or "").strip()
    return stored or "kumadesk-workshop-local"


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _server_shas() -> dict[str, str]:
    query = urllib.parse.urlencode({"action": "manifest"})
    request = urllib.request.Request(
        f"{MODELS_API}?{query}",
        headers={"X-Workshop-Token": _token()},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        return {}
    found: dict[str, str] = {}
    for item in payload.get("files") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("path") or "")
        sha = str(item.get("sha1") or "")
        if name and sha:
            found[name] = sha
    return found


def _download(name: str, dest: Path, remote_sha: str) -> None:
    query = urllib.parse.urlencode({"action": "file", "path": name})
    request = urllib.request.Request(
        f"{MODELS_API}?{query}",
        headers={"X-Workshop-Token": _token()},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        header_sha = str(response.headers.get("X-Workshop-Sha1") or "")
        data = response.read()
    digest = hashlib.sha1(data).hexdigest()
    expect = header_sha or remote_sha
    if expect and digest != expect:
        raise RuntimeError("受け取ったモデルがサーバーのモデルと違います。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(".pt.part")
    temporary.write_bytes(data)
    temporary.replace(dest)


def coin_models_differ() -> bool:
    remote = _server_shas()
    for name in COIN_MODEL_NAMES:
        remote_sha = remote.get(name, "")
        if not remote_sha:
            continue
        dest = _MODELS_DIR / name
        local_sha = _sha1(dest) if dest.is_file() else ""
        if local_sha != remote_sha:
            return True
    return False


def sync_coin_models() -> list[str]:
    remote = _server_shas()
    updated: list[str] = []
    for name in COIN_MODEL_NAMES:
        remote_sha = remote.get(name, "")
        if not remote_sha:
            continue
        dest = _MODELS_DIR / name
        local_sha = _sha1(dest) if dest.is_file() else ""
        if local_sha == remote_sha:
            continue
        _download(name, dest, remote_sha)
        updated.append(name)
    return updated


class CoinModelCheckWorker(QThread):
    checked = Signal(bool)

    def run(self) -> None:
        try:
            differs = coin_models_differ()
        except (OSError, json.JSONDecodeError, UnicodeError, RuntimeError, urllib.error.URLError):
            differs = False
        self.checked.emit(differs)


class CoinModelSyncWorker(QThread):
    updated = Signal(list)
    failed = Signal()

    def run(self) -> None:
        try:
            names = sync_coin_models()
        except (OSError, json.JSONDecodeError, UnicodeError, RuntimeError, urllib.error.URLError):
            self.failed.emit()
            return
        self.updated.emit(names)
