from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QVBoxLayout,
    QWidget,
)

LOCAL_API = "http://localhost:8888/my_home_page/workshop_data/api.php"
PROD_API = "https://hokkai-syabusyabu.com/home_page/workshop_data/api.php"
DEFAULT_TOKEN = "kumadesk-workshop-local"
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
UPLOAD_WORKERS = 6


def settings() -> QSettings:
    return QSettings("workshop", "WorkshopDataServer")


def api_url() -> str:
    stored = str(settings().value("api_url", "") or "").strip()
    return stored or LOCAL_API


def api_token() -> str:
    stored = str(settings().value("api_token", "") or "").strip()
    return stored or DEFAULT_TOKEN


def _skip(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return any(part in SKIP_NAMES for part in path.parts)


def iter_local_files(root: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file() or _skip(path):
            continue
        rel = path.relative_to(root).as_posix()
        files.append((rel, path))
    return files


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _request(action: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    query = urllib.parse.urlencode({"action": action})
    url = f"{api_url()}?{query}"
    req_headers = {"X-Workshop-Token": api_token()}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = str(response.headers.get("Content-Type") or "")
            return response.status, body, content_type
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return exc.code, body, str(exc.headers.get("Content-Type") or "")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"サーバーに接続できませんでした。\n{exc.reason}") from exc


def ping() -> dict:
    status, body, _ctype = _request("ping")
    payload = _json(body)
    if status != 200 or not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or f"接続できませんでした（{status}）"))
    return payload


def _json(body: bytes) -> dict:
    text = body.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except Exception as exc:
        preview = " ".join(text.split())[:240]
        if not preview:
            raise RuntimeError("サーバーの応答が空でした") from exc
        raise RuntimeError(f"サーバーの応答が JSON ではありません。\n{preview}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("サーバーの応答が不正です")
    return payload


def _php_bytes(value: object) -> int | None:
    text = str(value or "").strip().upper().replace(" ", "")
    if not text:
        return None
    unit = 1
    if text.endswith("G"):
        unit = 1024 ** 3
        text = text[:-1]
    elif text.endswith("M"):
        unit = 1024 ** 2
        text = text[:-1]
    elif text.endswith("K"):
        unit = 1024
        text = text[:-1]
    try:
        return int(float(text) * unit)
    except ValueError:
        return None


def upload_limit_bytes() -> int | None:
    try:
        info = ping()
    except Exception:
        return None
    sizes = [
        _php_bytes(info.get("post_max_size")),
        _php_bytes(info.get("upload_max_filesize")),
    ]
    sizes = [item for item in sizes if item]
    return min(sizes) if sizes else None


def manifest() -> list[dict]:
    status, body, _ctype = _request("manifest")
    payload = _json(body)
    if status != 200 or not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "一覧を取得できませんでした"))
    files = payload.get("files") or []
    return files if isinstance(files, list) else []


def download_file(rel: str, dest: Path) -> None:
    query = urllib.parse.urlencode({"action": "file", "path": rel})
    url = f"{api_url()}?{query}"
    request = urllib.request.Request(url, headers={"X-Workshop-Token": api_token()})
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            dest.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{rel} を取得できませんでした。\n{detail}") from exc


def _multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----WorkshopBoundary7MA4YWxkTrZu0gW"
    lines = []
    for key, value in fields.items():
        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(f'Content-Disposition: form-data; name="{key}"'.encode("utf-8"))
        lines.append(b"")
        lines.append(value.encode("utf-8"))
    lines.append(f"--{boundary}".encode("utf-8"))
    lines.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8")
    )
    lines.append(b"Content-Type: application/octet-stream")
    lines.append(b"")
    body = b"\r\n".join(lines) + b"\r\n" + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def upload_file(rel: str, path: Path) -> None:
    content = path.read_bytes()
    body, content_type = _multipart({"action": "put", "path": rel}, path.name, content)
    status, raw, _ctype = _request(
        "put",
        data=body,
        headers={"Content-Type": content_type},
        timeout=180,
    )
    try:
        payload = _json(raw)
    except RuntimeError as exc:
        raise RuntimeError(f"{rel}\n{exc}") from exc
    if status != 200 or not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or f"{rel} を送れませんでした"))


def prune(keep: list[str]) -> None:
    body = json.dumps({"keep": keep}, ensure_ascii=False).encode("utf-8")
    status, raw, _ctype = _request(
        "prune",
        data=body,
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
    payload = _json(raw)
    if status != 200 or not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "余分なファイルを消せませんでした"))


def format_upload_report(report: dict | int, extra: str = "") -> tuple[str, str]:
    if not isinstance(report, dict):
        report = {"sent": int(report or 0)}
    sent = int(report.get("sent") or 0)
    remaining = int(report.get("remaining") or 0)
    oversized = [str(item) for item in report.get("oversized") or []]
    paused = bool(report.get("paused"))
    extra_line = f"\n{extra.strip()}" if extra.strip() else ""
    over_text = ""
    if oversized:
        listed = "\n".join(oversized[:8])
        more = f"\nほか {len(oversized) - 8} 件" if len(oversized) > 8 else ""
        over_text = f"\n上限より大きいので見送りました:\n{listed}{more}"
    if paused:
        return (
            "途中まで送りました",
            (
                f"{sent} 件送りました。PHPのアップロード上限の手前で止めています。"
                f"\n残り {remaining} 件は、もう一度「サーバーに保存」を押すと続きから送ります。"
                f"{over_text}{extra_line}"
            ),
        )
    if oversized:
        return (
            "一部送れませんでした",
            f"{sent} 件送りました。{over_text}{extra_line}",
        )
    return (
        "サーバーに保存しました",
        f"画像とモデルをサーバーに送りました。更新 {sent} 件{extra_line}",
    )


def upload_data_dir(root: Path, progress=None) -> dict:
    files = iter_local_files(root)
    remote = {
        str(item.get("path")): (str(item.get("sha1") or ""), int(item.get("size") or 0))
        for item in manifest()
    }
    limit = upload_limit_bytes() or 32 * 1024 * 1024
    overhead = 64 * 1024
    budget = max(limit - overhead, 1024 * 1024)
    skipped = 0
    oversized: list[str] = []
    keep: list[str] = []
    to_send: list[tuple[str, Path]] = []
    for rel, path in files:
        keep.append(rel)
        size = path.stat().st_size
        if size + overhead > budget:
            oversized.append(rel)
            continue
        meta = remote.get(rel)
        if meta is not None and meta[1] == size and meta[0] == _sha1(path):
            skipped += 1
            continue
        to_send.append((rel, path))
    sent = 0
    total = max(len(to_send), 1)
    if progress is not None:
        progress(0, total, "準備できました")
    if to_send:
        with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
            futures = {pool.submit(upload_file, rel, path): rel for rel, path in to_send}
            done = 0
            first_error: BaseException | None = None
            for future in as_completed(futures):
                rel = futures[future]
                done += 1
                try:
                    future.result()
                    sent += 1
                except BaseException as exc:  # noqa: BLE001
                    if first_error is None:
                        first_error = exc
                if progress is not None:
                    progress(done, total, rel)
            if first_error is not None:
                raise first_error
    prune(keep)
    return {
        "sent": sent,
        "skipped": skipped,
        "remaining": 0,
        "paused": False,
        "oversized": oversized,
    }


def download_data_dir(dest: Path, progress=None) -> int:
    files = manifest()
    dest.mkdir(parents=True, exist_ok=True)
    total = max(len(files), 1)
    got = 0
    for index, item in enumerate(files, start=1):
        rel = str(item.get("path") or "")
        if not rel:
            continue
        if progress is not None:
            progress(index, total, rel)
        target = dest / rel
        if target.is_file() and _sha1(target) == str(item.get("sha1") or ""):
            continue
        download_file(rel, target)
        got += 1
    return got


def edit_settings(parent: QWidget | None = None) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("サーバー接続")
    layout = QVBoxLayout(dialog)
    hint = QLabel(
        "ローカルは localhost:8888 の my_home_page、本番は hokkai-syabusyabu.com の home_page です。"
        " token はサーバーの workshop_data/config.php と同じ値にしてください。"
    )
    hint.setWordWrap(True)
    layout.addWidget(hint)
    form = QFormLayout()
    place = QComboBox()
    place.addItem("このPC（ローカル）", LOCAL_API)
    place.addItem("本番サイト", PROD_API)
    place.addItem("URLを直接指定", "")
    url = QLineEdit(api_url())
    token = QLineEdit(api_token())
    token.setEchoMode(QLineEdit.EchoMode.Password)
    current = api_url()
    if current == LOCAL_API:
        place.setCurrentIndex(0)
    elif current == PROD_API:
        place.setCurrentIndex(1)
    else:
        place.setCurrentIndex(2)
    def _on_place(_index: int) -> None:
        data = place.currentData()
        if data:
            url.setText(str(data))
        url.setEnabled(not bool(data))
    place.currentIndexChanged.connect(_on_place)
    _on_place(place.currentIndex())
    form.addRow("場所", place)
    form.addRow("URL", url)
    form.addRow("token", token)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    chosen = url.text().strip()
    if not chosen:
        QMessageBox.information(parent, "URLがありません", "API の URL を入力してください。")
        return False
    settings().setValue("api_url", chosen)
    settings().setValue("api_token", token.text().strip() or DEFAULT_TOKEN)
    return True


def run_with_progress(parent: QWidget | None, title: str, work) -> object:
    dialog = QProgressDialog(title, None, 0, 0, parent)
    dialog.setWindowTitle(title)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(0)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()

    def progress(current: int, total: int, name: str) -> None:
        dialog.setMaximum(max(total, 1))
        dialog.setValue(current)
        dialog.setLabelText(f"{title}\n{name}")
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()

    try:
        return work(progress)
    finally:
        dialog.close()
