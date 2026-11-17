"""Read-only signals for known external ADB clients on Windows."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import os
from pathlib import Path
import subprocess


IS_WINDOWS = os.name == "nt"
ADB_SERVER_PORT = 5037


class OperatorProbeState(str, Enum):
    CLEAR = "clear"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class OperatorProbeUnknown(ValueError):
    """Raised when a TCP snapshot cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class OperatorProbeReport:
    state: OperatorProbeState
    observed_adb_client_pids: tuple[int, ...]
    external_adb_client_pids: tuple[int, ...]
    sampled_at: str
    reason: str | None = None


_TCP_STATES = frozenset({
    "CLOSED", "CLOSE_WAIT", "CLOSING", "ESTABLISHED", "FIN_WAIT_1",
    "FIN_WAIT_2", "LAST_ACK", "LISTENING", "SYN_RECEIVED", "SYN_SENT",
    "TIME_WAIT",
})


def _endpoint_port(value):
    try:
        host, port_text = value.rsplit(":", 1)
        port = int(port_text)
    except (AttributeError, ValueError):
        raise OperatorProbeUnknown("TCP快照地址格式未知") from None
    if not host or not 0 <= port <= 65535:
        raise OperatorProbeUnknown("TCP快照地址格式未知")
    return host.strip("[]"), port


def parse_netstat_tcp_snapshot(output):
    """Return PIDs of established clients connected to the default ADB server."""
    if not isinstance(output, str) or not output.strip():
        raise OperatorProbeUnknown("netstat没有返回可读快照")
    pids = set()
    saw_tcp_row = False
    saw_protocol_header = False
    for line in output.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0].casefold() in {"proto", "protocol", "protocolo", "protocole", "协议", "協議"}:
            saw_protocol_header = True
            continue
        if parts[0].upper() != "TCP":
            continue
        saw_tcp_row = True
        if len(parts) < 5:
            raise OperatorProbeUnknown("TCP快照记录不完整")
        _local_host, _local_port = _endpoint_port(parts[1])
        _remote_host, remote_port = _endpoint_port(parts[2])
        state = parts[3].upper()
        try:
            process_id = int(parts[4])
        except ValueError:
            raise OperatorProbeUnknown("TCP快照进程ID无效") from None
        if state not in _TCP_STATES or process_id < 0:
            raise OperatorProbeUnknown("TCP快照状态或进程ID未知")
        if remote_port == ADB_SERVER_PORT and state == "ESTABLISHED":
            if process_id == 0:
                raise OperatorProbeUnknown("ADB客户端进程ID不可见")
            pids.add(process_id)
    if not saw_tcp_row and not saw_protocol_header:
        raise OperatorProbeUnknown("netstat输出格式未知，不能确认TCP快照完整")
    return tuple(sorted(pids))


def _netstat_path():
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        return None
    candidate = Path(system_root) / "System32" / "netstat.exe"
    return candidate if candidate.is_file() else None


def scan_local_adb_clients(*, trusted_process_ids=(), timeout=3):
    """Take one read-only TCP snapshot; absence is not proof of exclusivity."""
    sampled_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    if not IS_WINDOWS:
        return OperatorProbeReport(
            OperatorProbeState.UNKNOWN, (), (), sampled_at,
            "当前平台不支持Windows TCP进程快照",
        )
    if type(timeout) not in (int, float) or timeout <= 0:
        raise ValueError("TCP快照超时必须大于零")
    try:
        trusted = set()
        for process_id in trusted_process_ids:
            if type(process_id) is not int or process_id <= 0:
                raise ValueError("受信任进程ID无效")
            trusted.add(process_id)
    except TypeError:
        raise ValueError("受信任进程ID列表无效") from None

    executable = _netstat_path()
    if executable is None:
        return OperatorProbeReport(
            OperatorProbeState.UNKNOWN, (), (), sampled_at,
            "无法定位Windows系统netstat工具",
        )
    try:
        result = subprocess.run(
            [str(executable), "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            timeout=float(timeout),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return OperatorProbeReport(
            OperatorProbeState.UNKNOWN, (), (), sampled_at,
            "本机TCP快照不可用",
        )
    if result.returncode != 0:
        return OperatorProbeReport(
            OperatorProbeState.UNKNOWN, (), (), sampled_at,
            "本机TCP快照返回失败",
        )
    try:
        observed = parse_netstat_tcp_snapshot(result.stdout)
    except OperatorProbeUnknown as error:
        return OperatorProbeReport(
            OperatorProbeState.UNKNOWN, (), (), sampled_at, str(error),
        )
    external = tuple(process_id for process_id in observed if process_id not in trusted)
    return OperatorProbeReport(
        OperatorProbeState.CONFLICT if external else OperatorProbeState.CLEAR,
        observed,
        external,
        sampled_at,
        "发现未登记的ADB服务器客户端" if external else None,
    )
