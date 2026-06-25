"""Windows Job Object that auto-kills every process this app ever spawns as
soon as the app process itself exits — for ANY reason, including being
force-closed (Task Manager "End Task", `taskkill /F`, a crash). That's a
kernel-enforced guarantee: no Python cleanup code needs to run, which matters
because a force-kill gives the process no chance to run any.

A process belonging to a job automatically pulls in every child it spawns
(`uv run acestep-api` -> the real python.exe -> its own worker subprocess,
etc.) unless a child explicitly opts out with CREATE_BREAKAWAY_FROM_JOB, which
none of the tools this app shells out to do — so assigning just the
top-level Popen handle is enough to cover the whole tree.

POSIX has no equivalent kernel primitive; `jobs.py` uses
`start_new_session=True` there instead so `terminate_tree` can reach the
whole process group on demand, but there's no OS-enforced "die with parent"
guarantee for a hard kill (covering that would need a per-child watchdog,
not worth it for a single-user desktop app).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_is_windows = sys.platform == "win32"

if _is_windows:
    _kernel32 = ctypes.windll.kernel32

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_ALL_ACCESS = 0x1F0FFF

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

_job_handle = None


def _ensure_job():
    global _job_handle
    if not _is_windows:
        return None
    if _job_handle is not None:
        return _job_handle
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _kernel32.SetInformationJobObject(
        handle, _JobObjectExtendedLimitInformation,
        ctypes.byref(info), ctypes.sizeof(info),
    )
    if not ok:
        _kernel32.CloseHandle(handle)
        return None
    _job_handle = handle
    return handle


def assign(pid: int) -> None:
    """Put `pid` under this app's kill-on-close job, so it (and everything it
    spawns) is guaranteed to die when this app process exits, however that
    happens. Best-effort and silent on failure — a job-object problem
    shouldn't break the feature that actually launched the subprocess."""
    if not _is_windows:
        return
    job = _ensure_job()
    if job is None:
        return
    proc_handle = _kernel32.OpenProcess(_PROCESS_ALL_ACCESS, False, pid)
    if not proc_handle:
        return
    try:
        _kernel32.AssignProcessToJobObject(job, proc_handle)
    finally:
        _kernel32.CloseHandle(proc_handle)
