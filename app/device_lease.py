"""Windows cross-process emulator leases and project-local diagnostics.

A dedicated owner thread holds the named mutex so release remains valid even
when the caller's worker thread changes. Diagnostic events stay under the
current project root; they contain no connection paths or ADB addresses.
"""

import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import time
from threading import Event, Lock, Thread

from .config import ROOT
from .device_identity import DeviceInstanceIdentity


class DeviceLeaseState(str, Enum):
    ACQUIRED = "acquired"
    CONFLICT = "conflict"
    ABANDONED = "abandoned"
    RELEASED = "released"


class DeviceLeaseError(RuntimeError):
    """Raised when lease state is unknown or recovery is required."""


class ProcessLiveness(str, Enum):
    ALIVE = "alive"
    EXITED = "exited"
    PID_REUSED = "pid_reused"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LeaseOwnerInfo:
    process_id: int
    thread_id: int
    process_created_filetime: int
    acquired_at: str
    identity_digest: str

    def to_dict(self):
        return {
            "schema_version": 1,
            "process_id": self.process_id,
            "thread_id": self.thread_id,
            "process_created_filetime": self.process_created_filetime,
            "acquired_at": self.acquired_at,
            "identity_digest": self.identity_digest,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            return None
        integer_fields = ("process_id", "thread_id", "process_created_filetime")
        if any(type(value.get(field)) is not int or value[field] <= 0 for field in integer_fields):
            return None
        acquired_at = value.get("acquired_at")
        digest = value.get("identity_digest")
        if not isinstance(acquired_at, str) or not acquired_at:
            return None
        if not isinstance(digest, str) or len(digest) != 64:
            return None
        return cls(
            process_id=value["process_id"],
            thread_id=value["thread_id"],
            process_created_filetime=value["process_created_filetime"],
            acquired_at=acquired_at,
            identity_digest=digest,
        )


class _FILETIME(ctypes.Structure):
    _fields_ = (("low", ctypes.c_uint32), ("high", ctypes.c_uint32))


_OWNER_MAPPING_SIZE = 4096
_PAGE_READWRITE = 0x04
_FILE_MAP_READ = 0x0004
_FILE_MAP_WRITE = 0x0002
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CreateFileMappingW.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_wchar_p,
    )
    kernel32.CreateFileMappingW.restype = ctypes.c_void_p
    kernel32.OpenFileMappingW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.OpenFileMappingW.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = (
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_size_t,
    )
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
    kernel32.UnmapViewOfFile.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
    )
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcessId.argtypes = ()
    kernel32.GetCurrentProcessId.restype = ctypes.c_uint32
    kernel32.GetCurrentThreadId.argtypes = ()
    kernel32.GetCurrentThreadId.restype = ctypes.c_uint32
    return kernel32


def _filetime_value(value):
    return (int(value.high) << 32) | int(value.low)


def _owner_mapping_name(identity):
    return f"Local\\MAA4BHC.DeviceLeaseOwner.v1.{identity.lease_key}"


def _read_owner_mapping(identity, *, timeout=0.0):
    if os.name != "nt":
        return None
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        kernel32 = _kernel32()
        ctypes.set_last_error(0)
        handle = kernel32.OpenFileMappingW(_FILE_MAP_READ, 0, _owner_mapping_name(identity))
        if handle:
            view = kernel32.MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, _OWNER_MAPPING_SIZE)
            try:
                if view:
                    raw = ctypes.string_at(view, _OWNER_MAPPING_SIZE).split(b"\0", 1)[0]
                    try:
                        value = json.loads(raw.decode("utf-8")) if raw else None
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        value = None
                    info = LeaseOwnerInfo.from_dict(value)
                    if info and info.identity_digest == identity.lease_key:
                        return info
            finally:
                if view:
                    kernel32.UnmapViewOfFile(view)
                kernel32.CloseHandle(handle)
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.02)


def _create_owner_mapping(kernel32, identity, info):
    name = _owner_mapping_name(identity)
    invalid_handle = ctypes.c_void_p(-1).value
    handle = kernel32.CreateFileMappingW(
        invalid_handle, None, _PAGE_READWRITE, 0, _OWNER_MAPPING_SIZE, name
    )
    if not handle:
        error = ctypes.get_last_error()
        raise DeviceLeaseError(f"无法发布租约诊断信息（Windows错误 {error}）")
    view = kernel32.MapViewOfFile(handle, _FILE_MAP_WRITE, 0, 0, _OWNER_MAPPING_SIZE)
    if not view:
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise DeviceLeaseError(f"无法映射租约诊断信息（Windows错误 {error}）")
    payload = json.dumps(info.to_dict(), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(payload) >= _OWNER_MAPPING_SIZE:
        kernel32.UnmapViewOfFile(view)
        kernel32.CloseHandle(handle)
        raise DeviceLeaseError("租约诊断信息超过共享缓冲区")
    ctypes.memset(view, 0, _OWNER_MAPPING_SIZE)
    ctypes.memmove(view, payload, len(payload))
    return handle, view


def _current_owner_info(kernel32, identity):
    created = _FILETIME()
    exited = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not kernel32.GetProcessTimes(
        kernel32.GetCurrentProcess(),
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        error = ctypes.get_last_error()
        raise DeviceLeaseError(f"无法读取租约持有者进程信息（Windows错误 {error}）")
    return LeaseOwnerInfo(
        process_id=int(kernel32.GetCurrentProcessId()),
        thread_id=int(kernel32.GetCurrentThreadId()),
        process_created_filetime=_filetime_value(created),
        acquired_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        identity_digest=identity.lease_key,
    )


def owner_process_liveness(info):
    """Check PID and creation time; access or API uncertainty remains unknown."""
    if not isinstance(info, LeaseOwnerInfo) or os.name != "nt":
        return ProcessLiveness.UNKNOWN
    kernel32 = _kernel32()
    ctypes.set_last_error(0)
    handle = kernel32.OpenProcess(
        _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION,
        0,
        info.process_id,
    )
    if not handle:
        return ProcessLiveness.EXITED if ctypes.get_last_error() == 87 else ProcessLiveness.UNKNOWN
    try:
        state = kernel32.WaitForSingleObject(handle, 0)
        if state == WindowsInstanceLease._WAIT_OBJECT_0:
            return ProcessLiveness.EXITED
        if state != WindowsInstanceLease._WAIT_TIMEOUT:
            return ProcessLiveness.UNKNOWN
        created = _FILETIME()
        exited = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return ProcessLiveness.UNKNOWN
        if _filetime_value(created) != info.process_created_filetime:
            return ProcessLiveness.PID_REUSED
        return ProcessLiveness.ALIVE
    finally:
        kernel32.CloseHandle(handle)


def read_local_lease_events(project_root, identity):
    """Read this project's append-only diagnostic events for one identity."""
    path = Path(project_root) / "runtime" / "logs" / "device-leases" / f"{identity.lease_key}.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError) as error:
        raise DeviceLeaseError("本机租约诊断记录不可读，已停止") from error
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise DeviceLeaseError("本机租约诊断记录损坏，已停止") from error
        if (not isinstance(event, dict) or event.get("schema_version") != 1
                or event.get("identity_digest") != identity.lease_key
                or event.get("event") not in ("acquired", "release_requested")
                or LeaseOwnerInfo.from_dict(event) is None
                or not isinstance(event.get("event_at"), str)):
            raise DeviceLeaseError("本机租约诊断记录身份不匹配，已停止")
        events.append(event)
    return tuple(events)


class WindowsInstanceLease:
    """Try to own a machine-wide mutex keyed only by stable device identity.

    The mutex owner is a private thread because Win32 mutexes are thread-owned.
    ``ABANDONED`` means a prior owner exited without releasing the mutex. This
    instance keeps the abandoned mutex quarantined; automatic recovery is not
    allowed by this primitive.
    """

    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_ABANDONED = 0x00000080
    _WAIT_TIMEOUT = 0x00000102
    _INFINITE = 0xFFFFFFFF

    def __init__(self, identity: DeviceInstanceIdentity, *, project_root=ROOT, startup_timeout=5):
        if not isinstance(identity, DeviceInstanceIdentity):
            raise TypeError("设备租约必须使用已确认的实例身份")
        if type(startup_timeout) not in (int, float) or startup_timeout <= 0:
            raise ValueError("租约启动超时必须大于零")
        self.project_root = Path(project_root).resolve()
        if not self.project_root.is_relative_to(ROOT.resolve()):
            raise ValueError("租约诊断记录必须保存在当前项目内")
        self.identity = identity
        self.startup_timeout = float(startup_timeout)
        self.name = f"Global\\MAA4BHC.DeviceLease.v1.{identity.lease_key}"
        self._ready = Event()
        self._release_requested = Event()
        self._guard = Lock()
        self._thread = None
        self._started = False
        self._state = None
        self._error = None
        self._wait_result = None
        self._owner_info = None
        self._mapping_handle = None
        self._mapping_view = None

    @property
    def diagnostic_path(self):
        return (self.project_root / "runtime" / "logs" / "device-leases"
                / f"{self.identity.lease_key}.jsonl")

    @property
    def owner_info(self):
        if self._owner_info is not None:
            return self._owner_info
        if self._state in (DeviceLeaseState.CONFLICT, DeviceLeaseState.ABANDONED):
            self._owner_info = _read_owner_mapping(self.identity, timeout=0.25)
        return self._owner_info

    @property
    def owner_liveness(self):
        return owner_process_liveness(self.owner_info)

    @property
    def state(self):
        return self._state

    def acquire(self):
        """Return ACQUIRED, CONFLICT, or ABANDONED; fail closed on API errors."""
        if os.name != "nt":
            raise DeviceLeaseError("当前平台不支持Windows设备租约")
        with self._guard:
            if self._started:
                raise DeviceLeaseError("同一租约对象不能重复获取")
            self._started = True
            self._thread = Thread(
                target=self._own_mutex,
                name="m4b-instance-lease",
                daemon=True,
            )
            self._thread.start()

        if not self._ready.wait(self.startup_timeout):
            raise DeviceLeaseError("设备租约状态检查超时，已阻止设备操作")
        if self._error is not None:
            raise DeviceLeaseError(self._error)
        if self._state is DeviceLeaseState.CONFLICT:
            self._owner_info = _read_owner_mapping(self.identity, timeout=0.25)
        return self._state

    def close(self):
        """Release a normally acquired lease; keep abandoned leases quarantined."""
        if self._state is DeviceLeaseState.ABANDONED:
            raise DeviceLeaseError("检测到上次任务异常退出；核对在途动作前不能释放设备租约")
        if self._state is not DeviceLeaseState.ACQUIRED:
            return
        self._append_event("release_requested")
        self._release_requested.set()
        self._thread.join(timeout=self.startup_timeout)
        if self._thread.is_alive():
            raise DeviceLeaseError("设备租约释放状态未知，已停止后续设备操作")
        if self._error is not None:
            raise DeviceLeaseError(self._error)
        self._state = DeviceLeaseState.RELEASED

    def _append_event(self, event):
        info = self._owner_info
        if info is None:
            raise DeviceLeaseError("租约持有者诊断信息缺失，无法确认状态")
        record = {
            "schema_version": 1,
            "event": event,
            **info.to_dict(),
            "event_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
        try:
            self.diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            with self.diagnostic_path.open("ab") as stream:
                stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise DeviceLeaseError("无法保存本机租约诊断记录，已阻止继续操作") from error

    def _own_mutex(self):
        handle = None
        owns_mutex = False
        quarantine = False
        kernel32 = None
        try:
            kernel32 = _kernel32()

            ctypes.set_last_error(0)
            handle = kernel32.CreateMutexW(None, 0, self.name)
            if not handle:
                error = ctypes.get_last_error()
                raise DeviceLeaseError(f"无法建立设备租约（Windows错误 {error}）")

            wait_result = kernel32.WaitForSingleObject(handle, 0)
            self._wait_result = wait_result
            if wait_result == self._WAIT_OBJECT_0:
                owns_mutex = True
                self._owner_info = _current_owner_info(kernel32, self.identity)
                self._mapping_handle, self._mapping_view = _create_owner_mapping(
                    kernel32, self.identity, self._owner_info
                )
                self._append_event("acquired")
                self._state = DeviceLeaseState.ACQUIRED
            elif wait_result == self._WAIT_ABANDONED:
                owns_mutex = True
                quarantine = True
                self._owner_info = _read_owner_mapping(self.identity)
                self._state = DeviceLeaseState.ABANDONED
            elif wait_result == self._WAIT_TIMEOUT:
                self._state = DeviceLeaseState.CONFLICT
                return
            else:
                error = ctypes.get_last_error()
                raise DeviceLeaseError(f"设备租约检查失败（Windows错误 {error}）")

            self._ready.set()
            self._release_requested.wait()
        except Exception as error:
            self._error = str(error)
        finally:
            if handle:
                if owns_mutex and not quarantine and not kernel32.ReleaseMutex(handle):
                    self._error = "Windows未能确认设备租约已释放"
                if self._mapping_view and not kernel32.UnmapViewOfFile(self._mapping_view):
                    self._error = "Windows未能关闭租约诊断映射"
                if self._mapping_handle and not kernel32.CloseHandle(self._mapping_handle):
                    self._error = "Windows未能关闭租约诊断句柄"
                if not kernel32.CloseHandle(handle):
                    self._error = "Windows未能关闭设备租约句柄"
            if self._state is None:
                self._state = DeviceLeaseState.CONFLICT
            self._ready.set()
