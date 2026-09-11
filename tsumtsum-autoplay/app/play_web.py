from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.paths import APP_ROOT

LOG_PATH = APP_ROOT / "data" / "play_log.jsonl"
PORT = 8766
REMOTE_API = "https://hokkai-syabusyabu.com/home_page/admin/tsumtsum_ai/api.php"
REMOTE_TOKEN = "kumadesk-workshop-local"
_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_plays() -> list[dict]:
    if not LOG_PATH.is_file():
        return []
    plays: list[dict] = []
    with _lock:
        text = LOG_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            plays.append(item)
    return plays


def append_play(
    clears: int,
    swipes: int,
    skills: int,
    skill_ok: int,
    coin: int | None,
    tsum: str = "",
    items: list[str] | None = None,
    duration: int | None = None,
    waits: list[float] | None = None,
) -> dict:
    item = {
        "at": _now(),
        "tsum": str(tsum or ""),
        "items": [str(name) for name in (items or []) if str(name)],
        "clears": int(clears),
        "swipes": int(swipes),
        "skills": int(skills),
        "skill_ok": int(skill_ok),
    }
    if duration is not None:
        item["duration"] = int(duration)
    shown_waits = _parse_waits(waits)
    if shown_waits:
        item["waits"] = shown_waits
    if coin is not None:
        item["coin"] = int(coin)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    threading.Thread(target=_post_remote, args=(item,), daemon=True).start()
    return item


def _post_remote(item: dict) -> None:
    body = dict(item)
    body["token"] = REMOTE_TOKEN
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        REMOTE_API,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Workshop-Token": REMOTE_TOKEN,
            "Authorization": f"Bearer {REMOTE_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return


def plays_payload() -> dict:
    return {"plays": load_plays()}


def page_html() -> str:
    plays = load_plays()
    rows = []
    coins = [int(item["coin"]) for item in plays if item.get("coin") is not None]
    avg = f"{sum(coins) / len(coins):.1f}" if coins else "—"
    for item in reversed(plays):
        skill = f"{int(item.get('skill_ok') or 0)}/{int(item.get('skills') or 0)}"
        coin = "—" if item.get("coin") is None else str(int(item["coin"]))
        at = str(item.get("at") or "")
        tsum = str(item.get("tsum") or "") or "—"
        names = item.get("items") or []
        if isinstance(names, str):
            shown_items = names or "—"
        else:
            shown_items = "、".join(str(name) for name in names if str(name)) or "—"
        duration = item.get("duration")
        time_text = "—" if duration is None else f"{int(duration)}秒"
        wait_text = _waits_text(item)
        rows.append(
            "<tr>"
            f"<td>{_esc(at)}</td>"
            f"<td>{_esc(tsum)}</td>"
            f"<td>{_esc(shown_items)}</td>"
            f"<td>{_esc(time_text)}</td>"
            f"<td>{_esc(wait_text)}</td>"
            f"<td>{int(item.get('clears') or 0)}</td>"
            f"<td>{int(item.get('swipes') or 0)}</td>"
            f"<td>{_esc(skill)}</td>"
            f"<td>{_esc(coin)}</td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan='9'>まだありません</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="8">
  <title>プレイ経過</title>
  <style>
    body {{ margin: 16px; background: #111; color: #eee; font-family: sans-serif; }}
    h1 {{ font-size: 20px; font-weight: 600; }}
    .sum {{ color: #bbb; margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #333; }}
    th {{ color: #888; font-weight: 500; }}
    td:nth-child(4), td:nth-child(5), td:nth-child(6), td:nth-child(7), td:nth-child(8), td:nth-child(9) {{ font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
  <h1>プレイ経過</h1>
  <p class="sum">試合 {len(plays)}　コイン平均 {avg}</p>
  <table>
    <thead>
      <tr><th>日時</th><th>ツム</th><th>アイテム</th><th>時間</th><th>LossTime</th><th>消し</th><th>なぞり</th><th>スキル</th><th>コイン</th></tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</body>
</html>
"""


def _parse_waits(value) -> list[float]:
    if not isinstance(value, list):
        return []
    shown: list[float] = []
    for part in value:
        try:
            shown.append(round(max(0.0, float(part)), 1))
        except (TypeError, ValueError):
            continue
    shown.sort(reverse=True)
    return shown[:3]


def _waits_text(item: dict) -> str:
    waits = _parse_waits(item.get("waits"))
    if not waits:
        return "—"
    return "LossTime / " + " ".join(f"{wait:.1f}s" for wait in waits)


def _parse_items(value) -> list[str]:
    if isinstance(value, str):
        parts = value.replace("、", ",").split(",")
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, list):
        return [str(name).strip() for name in value if str(name).strip()]
    return []


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, code: int, body: str | bytes, content_type: str) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/plays"):
            self._send(200, page_html(), "text/html; charset=utf-8")
            return
        if path == "/api/plays":
            self._send(
                200,
                json.dumps(plays_payload(), ensure_ascii=False),
                "application/json; charset=utf-8",
            )
            return
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/plays":
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, '{"ok":false}', "application/json; charset=utf-8")
            return
        if not isinstance(body, dict):
            self._send(400, '{"ok":false}', "application/json; charset=utf-8")
            return
        coin = body.get("coin")
        duration = body.get("duration")
        try:
            coin_n = None if coin is None or coin == "" else int(coin)
            duration_n = None if duration is None or duration == "" else int(duration)
            item = append_play(
                int(body.get("clears") or 0),
                int(body.get("swipes") or 0),
                int(body.get("skills") or 0),
                int(body.get("skill_ok") or 0),
                coin_n,
                str(body.get("tsum") or ""),
                _parse_items(body.get("items")),
                duration_n,
                _parse_waits(body.get("waits")),
            )
        except (TypeError, ValueError):
            self._send(400, '{"ok":false}', "application/json; charset=utf-8")
            return
        self._send(
            200,
            json.dumps({"ok": True, "play": item}, ensure_ascii=False),
            "application/json; charset=utf-8",
        )


def start_server(port: int = PORT) -> str:
    global _server, _thread
    stop_server()
    last_error = None
    for try_port in range(port, port + 5):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", try_port), _Handler)
        except OSError as exc:
            last_error = exc
            continue
        _server = server
        _thread = threading.Thread(target=server.serve_forever, daemon=True)
        _thread.start()
        return f"http://127.0.0.1:{try_port}/"
    raise RuntimeError(str(last_error or "経過のAPIを開けません"))


def stop_server() -> None:
    global _server, _thread
    server = _server
    _server = None
    _thread = None
    if server is None:
        return
    server.shutdown()
    server.server_close()


def url() -> str:
    if _server is None:
        return ""
    host, port = _server.server_address[:2]
    return f"http://{host}:{port}/"
