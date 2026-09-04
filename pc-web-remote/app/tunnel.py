from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from app.paths import DATA_DIR

_URL = re.compile(r"https://[a-zA-Z0-9.-]*pinggy[a-zA-Z0-9.-]*", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_KEY = DATA_DIR / "id_ed25519"
_KNOWN = DATA_DIR / "known_hosts"
_LOG = DATA_DIR / "tunnel.log"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def cloudflared_path() -> Path | None:
    return None


def ensure_key() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY.is_file():
        return _KEY
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(_KEY), "-q"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )
    if result.returncode != 0 or not _KEY.is_file():
        err = (result.stderr or result.stdout or "ssh-keygen に失敗しました").strip()
        raise RuntimeError(err)
    return _KEY


class Tunnel:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        self.url = ""
        self._logf = None

    def start(self, local_url: str) -> None:
        del local_url
        self.stop()
        key = ensure_key()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._logf = _LOG.open("w", encoding="utf-8", errors="replace", buffering=1)
        self.proc = subprocess.Popen(
            [
                "ssh",
                "-p",
                "443",
                "-i",
                str(key),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={_KNOWN}",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "ServerAliveCountMax=3",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "BatchMode=yes",
                "-T",
                "-R",
                "0:127.0.0.1:8765",
                "free.pinggy.io",
            ],
            stdout=self._logf,
            stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            self._logf.flush()
            text = _ANSI.sub("", _LOG.read_text(encoding="utf-8", errors="replace"))
            match = _URL.search(text)
            if match:
                self.url = match.group(0).rstrip(".,);")
                return
            if self.proc.poll() is not None:
                raise RuntimeError(text.strip()[-800:] or "公開トンネルが終了しました。")
            time.sleep(0.3)
        raise RuntimeError("公開用のアドレスが出ませんでした。")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self._logf is not None:
            self._logf.close()
            self._logf = None
        self.url = ""
