#!/usr/bin/env python3
"""Pulso — painel local de CPU, memória e disco."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import socket
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 8787
ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
SAMPLE_SECONDS = 2.0
HISTORY_LIMIT = 180
TOP_N = 15

LOCK = threading.Lock()
STATE: dict = {
    "collecting": True,
    "host": socket.gethostname(),
    "cpu": None,
    "memory": None,
    "disk_root": None,
    "history": [],
    "processes": {"by_cpu": [], "by_mem": []},
    "disk": {
        "status": "idle",
        "current": "",
        "error": "",
        "note": "",
        "started": None,
        "finished": None,
        "filesystems": [],
        "tree": [],
        "unattributed": 0,
    },
}
HISTORY: deque = deque(maxlen=HISTORY_LIMIT)
PREV_CPU: tuple[int, int, int] | None = None
PREV_PROC: dict[int, int] = {}
DISK_LOCK = threading.Lock()
USERS: dict[int, str] = {}


def now() -> float:
    return time.time()


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def user_name(uid: int) -> str:
    cached = USERS.get(uid)
    if cached is not None:
        return cached
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = str(uid)
    USERS[uid] = name
    return name


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def uptime_seconds() -> float:
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def load_average() -> list[float]:
    try:
        with open("/proc/loadavg", encoding="utf-8") as handle:
            parts = handle.read().split()
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except (OSError, ValueError, IndexError):
        return [0.0, 0.0, 0.0]


def read_aggregate_cpu() -> tuple[int, int, int]:
    with open("/proc/stat", encoding="utf-8") as handle:
        parts = handle.readline().split()[1:]
    values = [int(item) for item in parts]
    idle = values[3] if len(values) > 3 else 0
    iowait = values[4] if len(values) > 4 else 0
    return sum(values), idle, iowait


def task_ticks(pid: str, tid: str) -> int:
    try:
        with open(f"/proc/{pid}/task/{tid}/stat", encoding="utf-8", errors="replace") as handle:
            data = handle.read()
    except OSError:
        return 0
    end = data.rfind(")")
    if end < 0:
        return 0
    fields = data[end + 2 :].split()
    if len(fields) < 13:
        return 0
    try:
        return int(fields[11]) + int(fields[12])
    except ValueError:
        return 0


def friendly_name(cmd: str, fallback: str) -> str:
    if not cmd or cmd.startswith("["):
        return fallback
    parts = cmd.split()
    if not parts:
        return fallback
    exe = parts[0].rsplit("/", 1)[-1]
    if ".cursor-server" in cmd:
        if "--type=" in cmd:
            kind = cmd.split("--type=", 1)[1].split()[0]
            labels = {
                "fileWatcher": "arquivos",
                "extensionHost": "extensões",
                "ptyHost": "terminal",
            }
            return "Cursor (" + labels.get(kind, kind) + ")"
        if "server-main.js" in cmd:
            return "Cursor (servidor)"
        if "html-language-features" in cmd:
            return "Cursor (HTML)"
        if "json-language-features" in cmd:
            return "Cursor (JSON)"
        return "Cursor"
    if exe in {"node", "nodejs"}:
        script = next((item for item in parts[1:] if not item.startswith("-")), "")
        if script:
            return "node " + script.rsplit("/", 1)[-1][:48]
        return "node"
    if exe.startswith("python"):
        script = next((item for item in parts[1:] if not item.startswith("-")), "")
        if script:
            return exe + " " + script.rsplit("/", 1)[-1]
        return exe
    if exe == "php":
        tail = [item for item in parts[1:4] if not item.startswith("-")]
        return ("php " + " ".join(tail))[:64] if tail else "php"
    return exe or fallback


def read_cmdline(pid: str, fallback: str) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read(2048)
    except OSError:
        return fallback
    text = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    return text or f"[{fallback}]"


def read_processes() -> list[dict]:
    found: list[dict] = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for pid in entries:
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8", errors="replace") as handle:
                status = handle.read()
        except OSError:
            continue
        name = pid
        rss = 0
        uid = 0
        for line in status.splitlines():
            if line.startswith("Name:"):
                name = line[5:].strip()
            elif line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    rss = int(parts[1]) * 1024
            elif line.startswith("Uid:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    uid = int(parts[1])
        ticks = 0
        try:
            for tid in os.listdir(f"/proc/{pid}/task"):
                ticks += task_ticks(pid, tid)
        except OSError:
            continue
        cmd = read_cmdline(pid, name)
        found.append(
            {
                "pid": int(pid),
                "user": user_name(uid),
                "name": friendly_name(cmd, name),
                "cmd": cmd,
                "rss": rss,
                "ticks": ticks,
            }
        )
    return found


def root_disk() -> dict:
    stats = os.statvfs("/")
    frsize = stats.f_frsize or stats.f_bsize
    total = stats.f_blocks * frsize
    used = (stats.f_blocks - stats.f_bfree) * frsize
    avail = stats.f_bavail * frsize
    base = used + avail
    percent = (used / base * 100) if base else 0.0
    return {
        "mount": "/",
        "total": total,
        "used": used,
        "avail": avail,
        "percent": round(percent, 1),
    }


def read_memory() -> dict:
    info: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            number = rest.strip().split()
            if number and number[0].isdigit():
                info[key] = int(number[0]) * 1024
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    used = max(total - available, 0)
    percent = (used / total * 100) if total else 0.0
    return {
        "total": total,
        "used": used,
        "available": available,
        "percent": round(percent, 1),
        "swap_total": swap_total,
        "swap_used": max(swap_total - swap_free, 0),
    }


def snapshot(previous_cpu: tuple[int, int, int] | None, previous_proc: dict[int, int]):
    total, idle, iowait = read_aggregate_cpu()
    processes = read_processes()
    cores = os.cpu_count() or 1
    machine_pct = 0.0
    iowait_pct = 0.0
    total_delta = 0
    if previous_cpu is not None:
        total_delta = total - previous_cpu[0]
        idle_delta = idle - previous_cpu[1]
        iowait_delta = iowait - previous_cpu[2]
        if total_delta > 0:
            machine_pct = max(total_delta - idle_delta - iowait_delta, 0) / total_delta * 100
            iowait_pct = max(iowait_delta, 0) / total_delta * 100

    ranked = []
    next_proc: dict[int, int] = {}
    for proc in processes:
        pid = proc["pid"]
        ticks = proc["ticks"]
        next_proc[pid] = ticks
        cpu = 0.0
        if previous_cpu is not None and pid in previous_proc and total_delta > 0:
            cpu = (ticks - previous_proc[pid]) / total_delta * 100 * cores
            cpu = max(cpu, 0.0)
        item = {
            "pid": pid,
            "user": proc["user"],
            "name": proc["name"],
            "cmd": proc["cmd"][:240],
            "rss": proc["rss"],
            "cpu": round(cpu, 1),
        }
        ranked.append(item)

    by_cpu = sorted(ranked, key=lambda item: item["cpu"], reverse=True)[:TOP_N]
    by_mem = sorted(ranked, key=lambda item: item["rss"], reverse=True)[:TOP_N]
    memory = read_memory()
    disk = root_disk()
    live = {
        "collecting": previous_cpu is None,
        "updated": now(),
        "host": socket.gethostname(),
        "uptime": uptime_seconds(),
        "cpu": {
            "percent": round(machine_pct, 1),
            "iowait": round(iowait_pct, 1),
            "cores": cores,
            "model": cpu_model(),
            "load": load_average(),
        },
        "memory": memory,
        "disk_root": disk,
        "processes": {"by_cpu": by_cpu, "by_mem": by_mem},
    }
    return live, (total, idle, iowait), next_proc


def publish_live(live: dict) -> None:
    if not live["collecting"]:
        HISTORY.append(
            {
                "t": live["updated"],
                "cpu": live["cpu"]["percent"],
                "mem": live["memory"]["percent"],
                "disk": live["disk_root"]["percent"],
            }
        )
    with LOCK:
        STATE["collecting"] = live["collecting"]
        STATE["updated"] = live["updated"]
        STATE["host"] = live["host"]
        STATE["uptime"] = live["uptime"]
        STATE["cpu"] = live["cpu"]
        STATE["memory"] = live["memory"]
        STATE["disk_root"] = live["disk_root"]
        STATE["processes"] = live["processes"]
        STATE["history"] = list(HISTORY)


def sampler() -> None:
    global PREV_CPU, PREV_PROC
    try:
        live, PREV_CPU, PREV_PROC = snapshot(None, {})
        publish_live(live)
    except Exception as exc:  # noqa: BLE001 - keep the sampler alive
        with LOCK:
            STATE["sampler_error"] = str(exc)
    time.sleep(1.0)
    while True:
        try:
            live, PREV_CPU, PREV_PROC = snapshot(PREV_CPU, PREV_PROC)
            publish_live(live)
        except Exception as exc:  # noqa: BLE001 - keep the sampler alive
            with LOCK:
                STATE["sampler_error"] = str(exc)
        time.sleep(SAMPLE_SECONDS)


def interesting_mounts() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        source, target, fstype = parts[0], parts[1], parts[2]
        if target == "/":
            found.append((source, target, fstype))
            continue
        if fstype == "9p" and target.startswith("/mnt/") and target.count("/") == 2:
            found.append((source, target, fstype))
    return found


def statvfs_limited(path: str, timeout: float = 1.5):
    box: dict = {}

    def run() -> None:
        try:
            box["st"] = os.statvfs(path)
        except Exception as exc:  # noqa: BLE001
            box["err"] = str(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None
    return box.get("st")


def filesystem_usage() -> list[dict]:
    rows = []
    seen: set[str] = set()
    for _source, target, fstype in interesting_mounts():
        if target in seen:
            continue
        seen.add(target)
        stats = statvfs_limited(target)
        if stats is None:
            rows.append(
                {
                    "mount": target,
                    "type": fstype,
                    "label": mount_label(target, fstype),
                    "windows": fstype == "9p",
                    "total": 0,
                    "used": 0,
                    "avail": 0,
                    "percent": 0,
                    "unavailable": True,
                }
            )
            continue
        frsize = stats.f_frsize or stats.f_bsize
        total = stats.f_blocks * frsize
        used = (stats.f_blocks - stats.f_bfree) * frsize
        avail = stats.f_bavail * frsize
        base = used + avail
        percent = (used / base * 100) if base else 0.0
        rows.append(
            {
                "mount": target,
                "type": fstype,
                "label": mount_label(target, fstype),
                "windows": fstype == "9p",
                "total": total,
                "used": used,
                "avail": avail,
                "percent": round(percent, 1),
                "unavailable": False,
            }
        )
    return rows


def mount_label(target: str, fstype: str) -> str:
    if target == "/":
        return "Disco local"
    if fstype == "9p" and target.startswith("/mnt/") and len(target) == 6:
        return f"Windows {target[-1].upper()}:"
    return target


def run_du(path: str) -> tuple[list[tuple[int, str]], str]:
    try:
        proc = subprocess.run(
            ["nice", "-n", "19", "du", "-0", "-x", "-B1", "-d", "1", "--", path],
            capture_output=True,
            timeout=240,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], str(exc)
    stderr = proc.stderr.decode("utf-8", "replace")
    items: list[tuple[int, str]] = []
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if not record:
            continue
        size_text, sep, name = record.partition("\t")
        if not sep:
            continue
        try:
            items.append((int(size_text), name))
        except ValueError:
            continue
    return items, stderr


def build_nodes(path: str, depth: int, denied: list[int]) -> tuple[int, list[dict]]:
    with LOCK:
        STATE["disk"]["current"] = path
    items, stderr = run_du(path)
    denied[0] += stderr.lower().count("permission denied") + stderr.lower().count("permissão negada")
    total = 0
    children_raw: list[tuple[int, str]] = []
    for size, name in items:
        if name == path:
            total = size
        else:
            children_raw.append((size, name))
    if total <= 0:
        total = sum(size for size, _name in children_raw)
    children_raw = [
        item
        for item in children_raw
        if item[1] not in {"/mnt", "/proc", "/sys", "/dev", "/run", "/lost+found"}
    ]
    children_raw.sort(key=lambda item: item[0], reverse=True)
    significant = [item for item in children_raw if item[0] >= 50 * 1024 * 1024]
    shown = (significant or children_raw)[:8]
    nodes = []
    for index, (size, name) in enumerate(shown):
        child_nodes: list[dict] = []
        if (
            depth > 0
            and index < 4
            and size >= 50 * 1024 * 1024
            and not name.startswith("/mnt")
        ):
            _child_total, child_nodes = build_nodes(name, depth - 1, denied)
        nodes.append({"path": name, "size": size, "children": child_nodes})
    shown_sum = sum(size for size, _name in shown)
    rest = total - shown_sum
    if rest > 1024 * 1024 and children_raw:
        nodes.append({"path": f"{path} (resto)", "size": rest, "children": [], "remainder": True})
    return total, nodes


def docker_usage() -> dict:
    try:
        proc = subprocess.run(
            [
                "docker",
                "system",
                "df",
                "--format",
                "{{.Type}}\t{{.TotalCount}}\t{{.Active}}\t{{.Size}}\t{{.Reclaimable}}",
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc), "rows": []}
    if proc.returncode != 0:
        return {"available": False, "error": proc.stderr.strip()[:240], "rows": []}
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "type": parts[0],
                "total": parts[1],
                "active": parts[2],
                "size": parts[3],
                "reclaimable": parts[4],
            }
        )
    return {"available": bool(rows), "error": "", "rows": rows}


def disk_scan() -> None:
    if not DISK_LOCK.acquire(blocking=False):
        return
    try:
        started = now()
        with LOCK:
            STATE["disk"]["status"] = "scanning"
            STATE["disk"]["error"] = ""
            STATE["disk"]["current"] = "/"
            STATE["disk"]["started"] = started
        filesystems = filesystem_usage()
        docker_info = docker_usage()
        with LOCK:
            STATE["disk"]["filesystems"] = filesystems
            STATE["disk"]["docker"] = docker_info
        denied = [0]
        visible, tree = build_nodes("/", 2, denied)
        root = root_disk()
        unattributed = max(root["used"] - visible, 0)
        note = ""
        if docker_info.get("available"):
            note = (
                "Imagens, volumes e cache do Docker ficam em /var/lib/docker, "
                "pasta que este usuário não consegue listar. Os números do Docker vêm do daemon."
            )
        with LOCK:
            STATE["disk"].update(
                {
                    "status": "ready",
                    "current": "",
                    "error": "",
                    "note": note.strip(),
                    "finished": now(),
                    "filesystems": filesystems,
                    "docker": docker_info,
                    "tree": tree,
                    "unattributed": unattributed,
                    "visible": visible,
                }
            )
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            STATE["disk"]["status"] = "error"
            STATE["disk"]["error"] = str(exc)
            STATE["disk"]["current"] = ""
            STATE["disk"]["finished"] = now()
    finally:
        DISK_LOCK.release()


def public_state() -> dict:
    with LOCK:
        payload = json.loads(json.dumps(STATE))
    payload["updated"] = iso(payload.get("updated"))
    disk = payload.get("disk") or {}
    disk["started"] = iso(disk.get("started"))
    disk["finished"] = iso(disk.get("finished"))
    return payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._file(INDEX, "text/html; charset=utf-8")
            return
        if path == "/api/stats":
            self._json(public_state())
            return
        self._json({"error": "não encontrado"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/disk/refresh":
            started = DISK_LOCK.locked()
            if not started:
                threading.Thread(target=disk_scan, daemon=True).start()
            self._json({"ok": True, "already": started})
            return
        self._json({"error": "não encontrado"}, status=404)

    def log_message(self, fmt: str, *args) -> None:
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"error": "página indisponível"}, status=500)
            return
        self._send(200, content_type, body)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def lan_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        output = subprocess.check_output(["ip", "-4", "-br", "addr"], text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return addresses
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        iface = parts[0]
        if iface == "lo" or iface.startswith(("docker", "br-", "veth")):
            continue
        for token in parts[2:]:
            ip = token.split("/", 1)[0]
            if ip.startswith("169.254.") or ":" in ip:
                continue
            addresses.append(ip)
    return addresses


def serve(host: str = HOST, port: int = PORT) -> None:
    threading.Thread(target=sampler, daemon=True).start()
    threading.Thread(target=disk_scan, daemon=True).start()
    class Server(ThreadingHTTPServer):
        allow_reuse_address = True

    server = Server((host, port), Handler)
    urls = [f"http://127.0.0.1:{port}"] + [f"http://{ip}:{port}" for ip in lan_addresses()]
    (ROOT / "server.pid").write_text(str(os.getpid()))
    print("Pulso", flush=True)
    for url in urls:
        print(url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pulso — painel local de CPU, memória e disco.",
    )
    parser.add_argument(
        "--host",
        default=HOST,
        help="endereço de escuta (padrão: 0.0.0.0, para o navegador do Windows alcançar a WSL)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=PORT,
        help="porta HTTP (padrão: 8787)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    serve(arguments.host, arguments.port)
