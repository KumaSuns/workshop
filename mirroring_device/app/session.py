from __future__ import annotations

import socket
import struct
import subprocess
import sys
import threading

from PySide6.QtCore import QThread, Signal

TCP_PORT = 47777
BEACON_PORT = 47778
RECEIVER_NAME = "このPC"


class MirrorSession(QThread):
    status = Signal(str)
    ready = Signal()
    pcm = Signal(bytes)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._latest: bytes | None = None
        self._pending = False
        self._stop = False
        self._server: socket.socket | None = None
        self._beacon: socket.socket | None = None
        self._client: socket.socket | None = None

    def take_frame(self) -> bytes | None:
        with self._lock:
            frame = self._latest
            self._latest = None
            if frame is None:
                self._pending = False
            return frame

    def stop(self) -> None:
        self._stop = True
        server = self._server
        beacon = self._beacon
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        if beacon is not None:
            try:
                beacon.close()
            except OSError:
                pass
        client = self._client
        if client is not None:
            try:
                client.close()
            except OSError:
                pass

    def run(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", TCP_PORT))
            server.listen(1)
            server.settimeout(1.0)
            self._server = server
        except OSError as exc:
            self.status.emit("開けませんでした。 " + str(exc))
            return
        beacon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        beacon.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._beacon = beacon
        addresses = "  ".join(lan_addresses())
        self.status.emit("iPhone からの画面を待っています  " + addresses)
        packet = beacon_packet()
        targets = broadcast_addresses()
        while not self._stop:
            for address in targets:
                try:
                    beacon.sendto(packet, (address, BEACON_PORT))
                except OSError:
                    pass
            try:
                client, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client.settimeout(None)
            self._client = client
            self.status.emit("iPhone が接続しました")
            try:
                self._read_client(client)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
            if not self._stop:
                self.status.emit("切断されました。待っています")
        try:
            server.close()
        except OSError:
            pass

    def _read_client(self, client: socket.socket) -> None:
        while not self._stop:
            length_bytes = _read_exact(client, 4)
            length = struct.unpack(">I", length_bytes)[0]
            if length < 1 or length > 4_000_000:
                return
            body = _read_exact(client, length)
            kind = body[0]
            payload = body[1:]
            if kind == 1:
                self._offer(payload)
            elif kind == 2:
                self.pcm.emit(payload)

    def _offer(self, payload: bytes) -> None:
        with self._lock:
            self._latest = payload
            if self._pending:
                return
            self._pending = True
        self.ready.emit()


def _read_exact(client: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        part = client.recv(count - len(chunks))
        if not part:
            raise ConnectionError("closed")
        chunks += part
    return bytes(chunks)


def beacon_packet() -> bytes:
    name = RECEIVER_NAME.encode("utf-8")
    return b"MIRR" + struct.pack(">H", TCP_PORT) + name


def lan_addresses() -> list[str]:
    found: list[str] = []
    for address, _broadcast in _interfaces():
        if address.startswith("127.") or address.startswith("169.254."):
            continue
        if address not in found:
            found.append(address)
    return found


def broadcast_addresses() -> list[str]:
    found = ["255.255.255.255"]
    for _address, broadcast in _interfaces():
        if broadcast and broadcast not in found:
            found.append(broadcast)
    return found


def _interfaces() -> list[tuple[str, str]]:
    if sys.platform == "win32":
        return _windows_interfaces()
    return _unix_interfaces()


def _unix_interfaces() -> list[tuple[str, str]]:
    try:
        result = subprocess.run(["ifconfig"], capture_output=True, text=True, check=False)
    except OSError:
        return []
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] != "inet":
            continue
        address = parts[1]
        broadcast = ""
        if "broadcast" in parts:
            index = parts.index("broadcast")
            if index + 1 < len(parts):
                broadcast = parts[index + 1]
        rows.append((address, broadcast))
    return rows


def _windows_interfaces() -> list[tuple[str, str]]:
    try:
        result = subprocess.run(["ipconfig"], capture_output=True, text=True, check=False)
    except OSError:
        return []
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if "IPv4" not in line and "IP Address" not in line:
            continue
        if ":" not in line:
            continue
        address = line.split(":", 1)[1].strip()
        if address.count(".") == 3:
            rows.append((address, ""))
    return rows
