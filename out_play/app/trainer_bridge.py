from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Thread

from PySide6.QtGui import QImage

from PySide6.QtCore import QSettings

from app.paths import APP_ROOT

TRAINER_ROOT = APP_ROOT / "bundled" / "screen"
DIRECTML_DEVICE = False


def use_gpu() -> bool:
    stored = QSettings("workshop", "AutoPlay").value("use_gpu", True)
    if isinstance(stored, str):
        return stored.strip().lower() in {"1", "true", "yes", "on"}
    return bool(stored)


def _python_exe() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def _python_code(code: str) -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [_python_exe(), "-c", code],
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
    )
    return result.returncode


def _pip_text(result: subprocess.CompletedProcess[str]) -> str:
    text = f"{result.stderr or ''}\n{result.stdout or ''}".strip()
    if result.returncode == 0:
        return ""
    return text[-400:] if text else f"終了コード {result.returncode}"


def _install_directml() -> str:
    exe = _python_exe()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [exe, "-m", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )

    pip = run(["pip", "--version"])
    if pip.returncode != 0:
        boot = run(["ensurepip", "--upgrade"])
        if boot.returncode != 0:
            return _pip_text(boot) or _pip_text(pip) or "pip がありません"
    result = run(["pip", "install", "--disable-pip-version-check", "torch-directml"])
    return _pip_text(result)


_DIRECTML_PY = "3.12.10"
_DIRECTML_EMBED = (
    "https://www.python.org/ftp/python/"
    f"{_DIRECTML_PY}/python-{_DIRECTML_PY}-embed-amd64.zip"
)


def _python_can_directml() -> bool:
    return (
        sys.platform == "win32"
        and sys.maxsize > 2**32
        and (3, 8) <= sys.version_info[:2] <= (3, 12)
    )


def _runtime_python() -> Path:
    return APP_ROOT / "runtime" / "python312" / "python.exe"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as src, tmp.open("wb") as out:
            while True:
                chunk = src.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _prepare_embed(root: Path) -> None:
    pth = root / "python312._pth"
    lines = pth.read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if line.strip() not in {"import site", "# import site", "Lib\\site-packages"}
    ]
    kept.extend(["Lib\\site-packages", "import site"])
    pth.write_text("\n".join(kept) + "\n", encoding="utf-8")
    (root / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def _runtime_ready(exe: Path) -> bool:
    if not exe.is_file():
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(exe), "-c", "import PySide6, PIL, qrcode, torch_directml, torchvision"],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=flags,
    )
    return result.returncode == 0


def _install_runtime_packages(exe: Path) -> subprocess.CompletedProcess[str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        [
            str(exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "torch-directml",
            "torchvision",
            "PySide6",
            "Pillow",
            "qrcode",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        creationflags=flags,
    )


def _ensure_python312(report: Callable[[str], None] | None) -> str:
    exe = _runtime_python()
    if _runtime_ready(exe):
        return ""
    root = exe.parent
    try:
        if not exe.is_file():
            if report is not None:
                report(f"Python {_DIRECTML_PY} を入れています。")
            archive = root.parent / f"python-{_DIRECTML_PY}-embed-amd64.zip"
            _download(_DIRECTML_EMBED, archive)
            root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as packed:
                packed.extractall(root)
            _prepare_embed(root)
        if report is not None:
            report("Radeon用の部品を入れています")
        if not (root / "Lib" / "site-packages" / "pip").is_dir():
            get_pip = root / "get-pip.py"
            _download("https://bootstrap.pypa.io/get-pip.py", get_pip)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            pip_setup = subprocess.run(
                [str(exe), str(get_pip)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                creationflags=flags,
            )
            if pip_setup.returncode != 0:
                return _pip_text(pip_setup) or "pip を入れられませんでした。"
        installed = _install_runtime_packages(exe)
        if installed.returncode != 0 and not _runtime_ready(exe):
            return _pip_text(installed) or "Radeon用の部品を入れられませんでした。"
    except Exception as exc:
        return str(exc).strip() or "Python 3.12 を入れられませんでした。"
    if not _runtime_ready(exe):
        return "Radeon用の部品を入れられませんでした。"
    return ""


def _relaunch_with(exe: Path) -> None:
    main = APP_ROOT / "main.py"
    waiter = APP_ROOT / "runtime" / "relaunch.py"
    waiter.parent.mkdir(parents=True, exist_ok=True)
    waiter.write_text(
        "import os, subprocess, sys, time\n"
        "pid = int(sys.argv[1])\n"
        "while True:\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "    except OSError:\n"
        "        break\n"
        "    time.sleep(0.2)\n"
        "subprocess.Popen([sys.argv[2], sys.argv[3], *sys.argv[5:]], cwd=sys.argv[4])\n",
        encoding="utf-8",
    )
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, name, 0)
    subprocess.Popen(
        [
            sys.executable,
            str(waiter),
            str(os.getpid()),
            str(exe),
            str(main),
            str(APP_ROOT),
            *sys.argv[1:],
        ],
        creationflags=flags,
        close_fds=True,
    )
    os._exit(0)


def _switch_to_python312(report: Callable[[str], None] | None) -> str:
    exe = _runtime_python()
    if Path(sys.executable).resolve() == exe.resolve():
        return ""
    note = _ensure_python312(report)
    if note:
        return note
    if report is not None:
        report("Python 3.12 で起動し直します。")
    _relaunch_with(exe)
    return ""


def _directml_device():
    import importlib

    sys.modules.pop("torch_directml", None)
    importlib.invalidate_caches()
    try:
        torch_directml = importlib.import_module("torch_directml")
    except Exception as exc:
        _directml_device.last_error = str(exc).strip() or exc.__class__.__name__
        return None
    chosen = None
    try:
        count = int(torch_directml.device_count())
    except Exception as exc:
        count = 0
        _directml_device.last_error = str(exc).strip() or exc.__class__.__name__
    if count >= 1:
        chosen = 0
        for index in range(count):
            try:
                name = str(torch_directml.device_name(index) or "")
            except Exception:
                name = ""
            if "radeon" in name.casefold():
                chosen = index
                break
    try:
        device = torch_directml.device() if chosen is None else torch_directml.device(chosen)
    except Exception as exc:
        _directml_device.last_error = str(exc).strip() or exc.__class__.__name__
        return None
    _directml_device.last_error = ""
    return device


_directml_device.last_error = ""


def _directml_name(device) -> str:
    index = int(getattr(device, "index", 0) or 0)
    try:
        import torch_directml

        name = str(torch_directml.device_name(index) or "").strip()
    except Exception:
        name = ""
    return name or "Radeon"


def _directml_probe(exe: str) -> str:
    code = r"""
import sys, traceback
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "bundled" / "screen"))
try:
    import torch
    import torch_directml
    from app.piece_model import PieceNet, adapt_piece_state
    device = torch_directml.device()
    path = root / "bundled" / "screen" / "data" / "models" / "pieces.pt"
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    model = PieceNet(pretrained=False)
    state = checkpoint["state_dict"] if isinstance(checkpoint, dict) and "state_dict" in checkpoint else checkpoint
    adapt_piece_state(model, state)
    model.to(device)
    print("ok")
except Exception:
    traceback.print_exc()
    sys.exit(1)
"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [exe, "-c", code, str(APP_ROOT)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=90,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return "モデルをRadeonへ移す試しが90秒で終わりませんでした。"
    except OSError as exc:
        return str(exc).strip() or "モデルをRadeonへ移す試しを開始できませんでした。"
    if result.returncode == 0:
        return "モデルをRadeonへ移す試しは成功しました。"
    text = f"{result.stderr or ''}\n{result.stdout or ''}".strip()
    tail = text[-400:] if text else "出力はありません。"
    return f"終了コード {result.returncode}\n{tail}"


def _resolve_play_device(report: Callable[[str], None] | None = None) -> tuple[object, str]:
    if not use_gpu():
        return "cpu", ""
    if _python_code("import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)") == 0:
        return "cuda", ""
    if not DIRECTML_DEVICE:
        runtime = _runtime_python()
        on_runtime = Path(sys.executable).resolve().parent == runtime.resolve().parent
        if on_runtime and _python_code("import torch_directml") == 0:
            device = _directml_device()
            if device is not None:
                return device, ""
            return "cpu", _directml_device.last_error or "DirectMLの装置がありません"
        if report is not None:
            report("Radeonへ移す試し")
        install_note = ""
        exe = _python_exe()
        if not _python_can_directml() or _python_code("import torch_directml") != 0:
            if _python_can_directml():
                if report is not None:
                    report("Radeon用の部品を入れています")
                install_note = _install_directml()
            if not _python_can_directml() or _python_code("import torch_directml") != 0:
                if report is not None:
                    report(f"Python {_DIRECTML_PY} を用意しています。")
                prepared = _ensure_python312(report)
                if prepared:
                    install_note = prepared if not install_note else install_note + "\n" + prepared
                if runtime.is_file():
                    exe = str(runtime)
        probed = _directml_probe(exe)
        if "成功しました" in probed:
            if Path(exe).resolve() == Path(_python_exe()).resolve():
                device = _directml_device()
                if device is not None:
                    return device, ""
            window = Path(exe).with_name("pythonw.exe")
            if report is not None:
                report("Radeonで予測するため、起動し直します。")
            _relaunch_with(window if window.is_file() else Path(exe))
        if install_note:
            probed = install_note + "\n" + probed
        return "cpu", probed
    if not _python_can_directml():
        note = _switch_to_python312(report)
        if Path(sys.executable).resolve() == _runtime_python().resolve():
            device = _directml_device()
            if device is not None:
                return device, ""
            return "cpu", note or _directml_device.last_error or "DirectMLの装置がありません"
        return "cpu", note
    device = _directml_device()
    install_error = ""
    if device is None:
        if report is not None:
            report("Radeon用の部品を入れています")
        install_error = _install_directml()
        device = _directml_device()
    if device is None:
        detail = install_error or _directml_device.last_error or "DirectMLの装置がありません"
        return "cpu", detail
    return device, ""


def _play_device():
    device, _note = _resolve_play_device()
    return device


def _remember_device(predictor, note: str) -> None:
    kind = getattr(predictor.device, "type", "")
    if kind == "privateuseone":
        predictor.device_label = _directml_name(predictor.device)
    else:
        predictor.device_label = str(predictor.device)
    predictor.device_note = note if predictor.device_label == "cpu" else ""


def load_play_tools(report: Callable[[str], None] | None = None) -> tuple[object, Callable, Callable]:
    device, note = _resolve_play_device(report)
    hidden = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "app" or key.startswith("app.")
    }
    root = str(TRAINER_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    predictor = None
    chain_fn = None
    keep: dict[str, object] = {}
    try:
        from app.dataset import Dataset
        from app.predictor import Predictor
        from app.tsum_chain import farthest_gap_ratio, tsum_chain_best_per_group

        models = TRAINER_ROOT / "data" / "models"
        piece_path = models / "pieces.pt"
        if not piece_path.is_file():
            raise FileNotFoundError(
                "ツムの〇モデルがありません。画面認識アプリで学習してください。"
            )
        predictor = Predictor(models, device=device)
        _remember_device(predictor, note)
        chain_fn = tsum_chain_best_per_group
        gap_fn = farthest_gap_ratio
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
        predictor._dataset_cls = Dataset
        predictor._trainer_modules = keep
        if getattr(predictor, "scene_model", None) is None:
            raise RuntimeError(
                "TIME UP のモデルがありません。動画フレーム抜き出しで GO / TIME UP を学習してください。"
            )
        return predictor, chain_fn, gap_fn
    finally:
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(hidden)
        if predictor is not None:
            predictor._trainer_modules = keep


PLAY_TRAIN_EPOCHS = 8


def train_play_models(predictor, stop=None) -> list[str]:
    hidden = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "app" or key.startswith("app.")
    }
    root = str(TRAINER_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    keep = dict(getattr(predictor, "_trainer_modules", None) or {})
    sys.modules.update(keep)
    ran: list[str] = []
    try:
        from app.dataset import Dataset
        from app.regions import PIECE_KEYS, SCENE_KEYS
        from app.train_worker import MIN_TRAIN_SAMPLES, TrainingCancelled, TrainWorker

        dataset = Dataset(TRAINER_ROOT / "data")
        jobs = _play_train_jobs(dataset, MIN_TRAIN_SAMPLES, PIECE_KEYS, SCENE_KEYS)
        if not jobs:
            return []
        if getattr(predictor, "release", None) is not None:
            predictor.release()
        worker = TrainWorker(jobs, epochs=PLAY_TRAIN_EPOCHS)
        inner = worker._raise_if_cancelled

        def _raise() -> None:
            if stop is not None and stop.is_set():
                raise TrainingCancelled()
            inner()

        worker._raise_if_cancelled = _raise
        try:
            worker._train()
            ran = [str(item[3] if len(item) > 3 else item[0]) for item in jobs]
        except TrainingCancelled:
            ran = []
        finally:
            worker._release_cuda()
            if getattr(predictor, "reload", None) is not None:
                predictor.reload(device=_play_device())
        return ran
    finally:
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
        if predictor is not None:
            predictor._trainer_modules = keep
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(hidden)


def _play_train_jobs(dataset, min_n, piece_keys, scene_keys) -> list[tuple]:
    jobs: list[tuple] = []
    piece_map = {
        sample.id: sample
        for key in piece_keys
        for sample in dataset.labeled_for(key)
    }
    piece_samples = list(piece_map.values())
    if len(piece_samples) >= min_n:
        type_samples = [
            sample
            for sample in piece_samples
            if len(
                {
                    int(piece.get("group") or 1)
                    for piece in sample.pieces
                    if str(piece.get("kind") or "") in {"tsum", "big"}
                }
            )
            >= 2
        ]
        if len(type_samples) >= min_n:
            jobs.append(("tsum_types", type_samples, dataset.model_path_for("tsum_types"), "ツムの種類"))
        jobs.append(("pieces", piece_samples, dataset.model_path_for("pieces"), "ツム・ボム・デカツム"))
    digit_samples = dataset.labeled_digit_samples()
    if len(digit_samples) >= min_n:
        jobs.append(("coin_digits", digit_samples, dataset.model_path_for("coin_digits"), "コインの数字"))
    playable = [sample for sample in dataset.all() if sample.status != "skipped"]
    others = sum(
        1
        for sample in playable
        if not any(key in sample.confirmed for key in scene_keys)
    )
    if (
        all(len(dataset.labeled_for(key)) >= min_n for key in scene_keys)
        and others >= min_n
    ):
        jobs.append(("scene", playable, dataset.model_path_for("scene"), "GO・TIME UP"))
    return jobs


def save_erase_lesson(
    predictor,
    image_path: Path,
    game: dict[str, int] | None,
    pieces: list[dict[str, int]],
) -> bool:
    dataset_cls = getattr(predictor, "_dataset_cls", None)
    if dataset_cls is None:
        return False
    data = Path(image_path).read_bytes()
    dataset = dataset_cls(TRAINER_ROOT / "data")
    sample = dataset._import_bytes(data, Path(image_path).suffix or ".png", "autoplay")
    regions = {}
    if game is not None:
        regions["game"] = {
            "x": int(game["x"]),
            "y": int(game["y"]),
            "w": int(game["w"]),
            "h": int(game["h"]),
        }
    dataset.set_regions(sample.id, regions, status="labeled", pieces=pieces)
    return True


HUD_KEYS = (
    "game",
    "score",
    "coin",
    "result_coin",
    "timer",
    "skill",
    "fan",
    "pause",
    "fever",
)
DIGIT_KEYS = ("coin", "result_coin")
RESULT_KEYS = ("result_coin", "score")
_board_queue: Queue | None = None
_board_thread: Thread | None = None
_board_dataset_cls = None


def save_play_board(
    predictor,
    image: QImage,
    game: dict[str, int] | None,
    boxes: dict[str, dict[str, int]] | None = None,
    pieces: list[dict[str, int]] | None = None,
    rgb=None,
) -> bool:
    hud = _hud_boxes(boxes, HUD_KEYS)
    if game is not None and "game" not in hud:
        hud["game"] = {
            "x": int(game["x"]),
            "y": int(game["y"]),
            "w": int(game["w"]),
            "h": int(game["h"]),
        }
    dataset_cls = getattr(predictor, "_dataset_cls", None)
    if dataset_cls is None:
        return False
    if rgb is None:
        return False
    kept = [
        {
            "x": int(piece["x"]),
            "y": int(piece["y"]),
            "r": int(piece["r"]),
            "kind": str(piece["kind"]),
            "group": int(piece.get("group") or 1),
        }
        for piece in (pieces or [])
        if int(piece.get("r") or 0) >= 4
    ]
    _ensure_board_saver(dataset_cls)
    _board_queue.put(
        {
            "rgb": rgb.copy(),
            "hud": hud,
            "pieces": kept,
        }
    )
    return True


def _ensure_board_saver(dataset_cls) -> None:
    global _board_queue, _board_thread, _board_dataset_cls
    _board_dataset_cls = dataset_cls
    if _board_queue is None:
        _board_queue = Queue()
    if _board_thread is not None and _board_thread.is_alive():
        return
    _board_thread = Thread(target=_board_save_loop, daemon=True)
    _board_thread.start()


def _board_save_loop() -> None:
    while True:
        job = _board_queue.get()
        try:
            _write_play_board(job)
        except Exception:
            pass


_BOARD_SAVE_SCRIPT = """
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from app.dataset import Dataset
meta = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
image = Path(meta["image"])
dataset = Dataset(root / "data")
before = len(dataset.all())
sample = dataset.import_file(image, save=False)
if sample is None or len(dataset.all()) <= before:
    raise SystemExit(0)
dataset.apply_predictions(sample.id, meta.get("hud") or {})
dataset.apply_piece_predictions(sample.id, meta.get("pieces") or [])
sample = dataset.get(sample.id)
if sample is None:
    raise SystemExit(0)
if hasattr(sample, "used_tsum"):
    sample.used_tsum = str(meta.get("used_tsum") or "")
    sample.used_tsum_id = str(meta.get("used_tsum_id") or "")
if meta.get("name_tsum"):
    token = str(getattr(sample, "used_tsum_id", "") or getattr(sample, "used_tsum", "") or "")
    if token:
        text = sample.source_name or "image.png"
        prefix = token + "_"
        if not text.casefold().startswith(prefix.casefold()):
            sample.source_name = prefix + text
sample.status = "predicted"
sample.confirmed = []
dataset.save()
"""


def _write_play_board(job: dict) -> None:
    rgb = job.get("rgb")
    if rgb is None:
        return
    fd, raw = tempfile.mkstemp(suffix=".png", prefix="bluestacks_")
    os.close(fd)
    tmp = Path(raw)
    meta_path = tmp.with_suffix(".json")
    try:
        rgb.save(tmp, format="PNG")
        meta_path.write_text(
            json.dumps(
                {
                    "image": str(tmp),
                    "hud": job.get("hud") or {},
                    "pieces": job.get("pieces") or [],
                    "used_tsum": job.get("used_tsum") or "",
                    "used_tsum_id": job.get("used_tsum_id") or "",
                    "name_tsum": bool(job.get("name_tsum")),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, "-c", _BOARD_SAVE_SCRIPT, str(TRAINER_ROOT), str(meta_path)],
            cwd=str(TRAINER_ROOT),
            check=False,
        )
    finally:
        tmp.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)


def save_play_scene(predictor, image: QImage, key: str) -> bool:
    return _save_labeled(predictor, image, {}, pieces=[], scene=key)


def save_play_result(predictor, image: QImage, boxes: dict[str, dict[str, int]] | None, rgb=None) -> bool:
    hud = _hud_boxes(boxes, RESULT_KEYS)
    if not hud:
        return False
    return _save_labeled(
        predictor,
        image,
        hud,
        pieces=[],
        readings=_digit_readings(predictor, rgb, hud),
        confirm_regions=False,
    )


def _hud_boxes(boxes: dict[str, dict[str, int]] | None, keys: tuple[str, ...]) -> dict[str, dict[str, int]]:
    hud: dict[str, dict[str, int]] = {}
    if not boxes:
        return hud
    for key in keys:
        box = boxes.get(key)
        if not box:
            continue
        hud[key] = {
            "x": int(box["x"]),
            "y": int(box["y"]),
            "w": int(box["w"]),
            "h": int(box["h"]),
        }
    return hud


def _digit_readings(predictor, rgb, boxes: dict[str, dict[str, int]]) -> dict[str, str]:
    readings: dict[str, str] = {}
    if rgb is None or not boxes:
        return readings
    for key in DIGIT_KEYS:
        box = boxes.get(key)
        if not box:
            continue
        try:
            crop = rgb.crop(
                (
                    int(box["x"]),
                    int(box["y"]),
                    int(box["x"]) + int(box["w"]),
                    int(box["y"]) + int(box["h"]),
                )
            )
            digits = "".join(
                char for char in str(predictor.predict_coin_digits(crop, key) or "") if char.isdigit()
            )
        except Exception:
            continue
        if digits:
            readings[key] = digits
    return readings


def _save_labeled(
    predictor,
    image: QImage,
    regions: dict[str, dict[str, int]],
    pieces: list[dict[str, int]] | None = None,
    readings: dict[str, str] | None = None,
    scene: str | None = None,
    confirm_regions: bool = True,
    rgb=None,
) -> bool:
    dataset_cls = getattr(predictor, "_dataset_cls", None)
    if dataset_cls is None or image is None or image.isNull():
        return False
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dataset = dataset_cls(TRAINER_ROOT / "data")
    before = len(dataset.all())
    sample = None
    if rgb is not None:
        fd, raw = tempfile.mkstemp(suffix=".png", prefix="bluestacks_")
        os.close(fd)
        tmp = Path(raw)
        try:
            rgb.save(tmp, format="PNG")
            sample = dataset.import_file(tmp, save=False)
        except Exception:
            sample = None
        finally:
            tmp.unlink(missing_ok=True)
    if sample is None:
        sample = dataset.import_qimage(
            image,
            source_name=f"bluestacks_{stamp}.png",
            name_prefix="bluestacks_",
        )
    if len(dataset.all()) <= before:
        return False
    status = "labeled" if confirm_regions or scene else "predicted"
    dataset.set_regions(sample.id, regions, status=status, pieces=pieces or [])
    if not confirm_regions and regions:
        sample = dataset.get(sample.id)
        if sample is not None:
            sample.confirmed = [key for key in sample.confirmed if key not in regions]
            sample.status = "predicted" if not scene else sample.status
            dataset.save()
    if readings:
        for key, digits in readings.items():
            try:
                dataset.set_reading(sample.id, key, digits)
            except Exception:
                continue
    if scene:
        dataset.confirm_key(sample.id, scene)
    return True
