"""Bound local processing, downloads and sleep inhibition for the roof pilot.

Limits are decimal GB: at most 20 GB in this project, stop below 25 GB free
on its drive. No user processes or persistent power settings are modified.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GB = 1_000_000_000
MAX_PROJECT_BYTES = 20 * GB
MIN_FREE_BYTES = 25 * GB
SIZE_MARGIN = 300_000_000
_cached_size = (0.0, 0)


class ResourceLimit(RuntimeError):
    pass


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in
        ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]


def memory_status():
    if os.name == "nt":
        value = MemoryStatus(); value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise ResourceLimit("Cannot read available system memory")
        return {"total": value.total, "available": value.available, "load_percent": value.load}
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, rest = line.split(':', 1); values[key] = int(rest.split()[0]) * 1024
    return {"total": values["MemTotal"], "available": values["MemAvailable"]}


def project_size():
    total = 0
    for base, directories, files in os.walk(ROOT, followlinks=False):
        keep = []
        for name in directories:
            p = Path(base, name)
            if name == '.git':
                continue
            try:
                info = p.lstat()
                if not (getattr(info, 'st_file_attributes', 0) & 0x400) and not p.is_symlink():
                    keep.append(name)
            except OSError:
                pass
        directories[:] = keep
        for name in files:
            try:
                total += Path(base, name).stat().st_size
            except FileNotFoundError:
                pass
    return total


def check_budget(reserve_bytes=0, *, force=False):
    global _cached_size
    free = shutil.disk_usage(ROOT).free
    if free < MIN_FREE_BYTES + reserve_bytes:
        raise ResourceLimit(f"STOP: free disk {free / GB:.2f} GB; need 25 GB plus reservation")
    if force or time.monotonic() - _cached_size[0] > 10:
        size = project_size()
        # Start the cache lifetime after the potentially slow filesystem walk.
        _cached_size = (time.monotonic(), size)
    size = _cached_size[1]
    if size + reserve_bytes + SIZE_MARGIN > MAX_PROJECT_BYTES:
        raise ResourceLimit(f"STOP: project {size / GB:.2f} GB plus reservation exceeds 20 GB budget")
    return {"free_disk_bytes": free, "project_bytes": size, "reserve_bytes": reserve_bytes}


@contextlib.contextmanager
def keep_awake():
    # Windows call belongs to the current thread and is reset when it exits.
    previous = None
    if os.name == 'nt':
        previous = ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        if not previous:
            raise ResourceLimit('Could not inhibit sleep for the worker')
    try:
        yield
    finally:
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(previous)


def download(url, destination, expected_sha256=None, max_bytes=2 * GB):
    """Bounded streaming download, atomic completion, preserves existing files."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if expected_sha256 and sha256(destination) != expected_sha256:
            raise ValueError(f'Existing file checksum mismatch: {destination}')
        return {"cached": True, "bytes": destination.stat().st_size, "seconds": 0, "url": url}
    check_budget(force=True)
    part = destination.with_name(destination.name + '.part')
    if part.exists():
        raise ValueError(f'Incomplete prior download exists; inspect before retrying: {part}')
    start = time.perf_counter(); received = 0; digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "TinyTowns-roof-pilot/1.0"})
    try:
        with keep_awake(), urllib.request.urlopen(request, timeout=90) as response:
            announced = int(response.headers.get('Content-Length', '0'))
            if announced > max_bytes:
                raise ResourceLimit(f'Download is {announced} bytes, greater than permitted maximum')
            check_budget(reserve_bytes=announced or max_bytes, force=True)
            with part.open('xb') as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block: break
                    received += len(block)
                    if received > max_bytes:
                        raise ResourceLimit('Download exceeded maximum size')
                    check_budget(reserve_bytes=max(0, announced - received))
                    output.write(block); digest.update(block)
            if announced and received != announced:
                raise IOError(f'Incomplete download: {received} / {announced}')
            if expected_sha256 and digest.hexdigest() != expected_sha256:
                raise ValueError('Downloaded checksum mismatch')
        part.replace(destination)
    except BaseException:
        # Only the partial file created by this invocation, never user data.
        if part.is_file(): part.unlink()
        raise
    return {"cached": False, "bytes": received, "seconds": time.perf_counter() - start,
            "url": url, "sha256": digest.hexdigest()}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_extract_zip(archive, destination):
    destination = Path(destination).resolve(); destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        files = z.infolist()
        check_budget(reserve_bytes=sum(i.file_size for i in files), force=True)
        for info in files:
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('ZIP path escapes destination')
            if info.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
            if target.exists():
                if target.stat().st_size != info.file_size:
                    raise ValueError(f'Existing extraction differs: {target}')
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + '.resource-guard-part')
            if partial.exists(): partial.unlink()  # This helper's interrupted extraction only.
            try:
                with z.open(info) as source, partial.open('xb') as output:
                    while block := source.read(1024 * 1024):
                        check_budget(); output.write(block)
                if partial.stat().st_size != info.file_size:
                    raise ValueError(f'Incomplete extraction: {target}')
                partial.replace(target)  # ZipExtFile checked CRC while reading to EOF.
            except BaseException:
                if partial.exists(): partial.unlink()
                raise


class _WindowsJob:
    """A nested Windows job limits the entire spawned process tree's commit."""
    def __init__(self, process, memory_limit):
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', ctypes.c_uint32), ('min_working', ctypes.c_size_t),
                        ('max_working', ctypes.c_size_t), ('active', ctypes.c_uint32),
                        ('affinity', ctypes.c_size_t), ('priority', ctypes.c_uint32),
                        ('scheduling', ctypes.c_uint32)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ['read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes']]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        self.Extended = Extended
        # Microsoft JOBOBJECT_BASIC_ACCOUNTING_INFORMATION (100 ns CPU ticks).
        # https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in
                        ('user_time', 'kernel_time', 'period_user', 'period_kernel')] + [
                        (name, ctypes.c_uint32) for name in
                        ('page_faults', 'total_processes', 'active_processes', 'terminated_processes')]
        self.Accounting = Accounting
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.restype = ctypes.c_void_p
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self.kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.kernel.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        self.kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        value = Extended(); value.basic.flags = 0x2000 | 0x200; value.job_memory = memory_limit
        self.kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        mask = ctypes.c_size_t(); system_mask = ctypes.c_size_t()
        if self.kernel.GetProcessAffinityMask(ctypes.c_void_p(int(process._handle)), ctypes.byref(mask), ctypes.byref(system_mask)):
            bits = [1 << i for i in range(ctypes.sizeof(ctypes.c_size_t)*8) if mask.value & (1 << i)]
            value.basic.affinity = sum(bits[:2]); value.basic.flags |= 0x10
        value.basic.priority = 0x4000; value.basic.flags |= 0x20  # BELOW_NORMAL_PRIORITY_CLASS
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(value), ctypes.sizeof(value)):
            raise OSError(ctypes.get_last_error(), 'Cannot install process-tree memory limit')
        if not self.kernel.AssignProcessToJobObject(self.handle, ctypes.c_void_p(int(process._handle))):
            self.close(); raise OSError(ctypes.get_last_error(), 'Cannot assign process-tree resource job')

    def peak(self):
        value = self.Extended()
        if not self.kernel.QueryInformationJobObject(self.handle, 9, ctypes.byref(value), ctypes.sizeof(value), None): return None
        return value.peak_job

    def accounting(self):
        value = self.Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            return {'cpu_seconds': None, 'cpu_accounting_error': ctypes.get_last_error()}
        return {'cpu_seconds': (value.user_time + value.kernel_time) / 10_000_000,
                'cpu_user_seconds': value.user_time / 10_000_000,
                'cpu_kernel_seconds': value.kernel_time / 10_000_000,
                'cpu_metric': 'Windows job user + kernel time, all associated processes; seconds',
                'process_count': value.total_processes}

    def terminate(self):
        if self.handle: self.kernel.TerminateJobObject(self.handle, 125)

    def close(self):
        if self.handle: self.kernel.CloseHandle(self.handle); self.handle = None


def run_guarded(cmd, cwd, log_path, min_available_gb=1.0, max_ram_gb=4.0,
                wait_memory_seconds=3600, reserve_bytes=0, env=None):
    log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
    start_wait = time.monotonic(); last_notice = 0
    check_budget(reserve_bytes, force=True)
    with keep_awake():
        while memory_status()['available'] < min_available_gb * GB:
            check_budget(reserve_bytes)
            if time.monotonic() - start_wait > wait_memory_seconds:
                raise ResourceLimit('Insufficient available RAM; task was not started')
            if time.monotonic() - last_notice > 30:
                print(f"Waiting for {min_available_gb:.1f} GB available RAM; currently {memory_status()['available']/GB:.2f} GB", flush=True)
                last_notice = time.monotonic()
            time.sleep(3)
        child_env = os.environ.copy()
        child_env.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','ARROW_NUM_THREADS','VECLIB_MAXIMUM_THREADS']})
        child_env.update({'PYTHONUTF8':'1','TINY_TOWNS_WORKERS':'1'})
        if env: child_env.update(env)
        before = check_budget(force=True); peak = None; job = None
        with log_path.open('w', encoding='utf-8') as log:
            start = time.perf_counter()
            process = subprocess.Popen(list(map(str,cmd)), cwd=cwd, env=child_env, stdout=log, stderr=subprocess.STDOUT)
            try:
                if os.name == 'nt': job = _WindowsJob(process, int(max_ram_gb * GB))
                while process.poll() is None:
                    check_budget()
                    if memory_status()['available'] < 250_000_000:
                        raise ResourceLimit('STOP: available system RAM below 250 MB')
                    if job: peak = job.peak()
                    try:
                        process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
                if job: peak = job.peak()
                result = {'command':list(map(str,cmd)), 'cwd':str(cwd), 'exit_code':process.returncode,
                          'elapsed_seconds':time.perf_counter()-start, 'peak_job_commit_bytes':peak,
                          'memory_metric':'Windows peak committed memory for entire child process tree',
                          'log':str(log_path), 'before':before,'after':check_budget(force=True)}
                if job: result.update(job.accounting())
                log_path.with_suffix(log_path.suffix+'.metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                if process.returncode: raise subprocess.CalledProcessError(process.returncode,cmd)
                return result
            except BaseException:
                if job: job.terminate()
                else: process.kill()
                process.wait(timeout=15)
                failure = {'command':list(map(str,cmd)), 'cwd':str(cwd),
                           'elapsed_seconds':time.perf_counter()-start,
                           'peak_job_commit_bytes':peak, 'error':str(sys.exc_info()[1]),
                           'exit_code':process.returncode}
                if job: failure.update(job.accounting())
                log_path.with_suffix(log_path.suffix+'.metrics.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
                raise
            finally:
                if job: job.close()


def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('status')
    r=sub.add_parser('run'); r.add_argument('--cwd',default=str(ROOT));r.add_argument('--log',required=True)
    r.add_argument('--min-available-gb',type=float,default=1);r.add_argument('--max-ram-gb',type=float,default=4)
    r.add_argument('--wait-memory-seconds',type=float,default=3600);r.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args()
    if a.action=='status': print(json.dumps({**check_budget(force=True),'memory':memory_status()},indent=2));return
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    print(json.dumps(run_guarded(command,a.cwd,a.log,a.min_available_gb,a.max_ram_gb,a.wait_memory_seconds),indent=2))


if __name__=='__main__':
    main()
