"""Bounded, cancellable LibreOffice PDF cache for Ubuntu previews."""
from pathlib import Path
import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time

OFFICE_EXTENSIONS = {'.xls', '.xlsx', '.xlsm', '.xltx', '.xltm', '.doc', '.docx', '.ppt', '.pptx'}
_LOCK = threading.Lock()
MAX_FILES = 900
MAX_BYTES = 3 * 1024 ** 3
TIMEOUT = 45

def executable():
    return shutil.which('libreoffice') or shutil.which('soffice')

def cache_root():
    return Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'mdir-u' / 'office-pdf-v1'

def cache_path(source):
    source = Path(source).resolve()
    stat = source.stat()
    key = f'{source}\0{stat.st_size}\0{stat.st_mtime_ns}\0libreoffice-v1'
    return cache_root() / (hashlib.sha256(key.encode()).hexdigest() + '.pdf')

def valid_pdf(path):
    try:
        with Path(path).open('rb') as stream:
            if stream.read(5) != b'%PDF-': return False
            stream.seek(max(0, Path(path).stat().st_size - 1024))
            return b'%%EOF' in stream.read()
    except OSError:
        return False

def prune():
    entries = []
    for path in cache_root().glob('*.pdf'):
        try:
            st = path.stat(); entries.append((st.st_mtime_ns, st.st_size, path))
        except OSError: pass
    total = sum(size for _, size, _ in entries)
    count = len(entries)
    for _, size, path in sorted(entries):
        if count <= MAX_FILES and total <= MAX_BYTES: break
        try:
            path.unlink(); total -= size; count -= 1
        except OSError: pass

def stop_process(process):
    if process.poll() is not None: return
    try:
        if os.name == 'posix': os.killpg(process.pid, signal.SIGTERM)
        else: process.terminate()
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            if os.name == 'posix': os.killpg(process.pid, signal.SIGKILL)
            else: process.kill()
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired): pass

def render_cached(source, *, cancel=None):
    """Return a cached PDF; return None when LibreOffice is not installed."""
    source = Path(source).resolve()
    cancel = cancel if cancel is not None else threading.Event()
    if cancel.is_set(): raise RuntimeError('Preview cancelled')
    target = cache_path(source)
    if valid_pdf(target): return target
    binary = executable()
    if not binary: return None
    if source.stat().st_size > 256 * 1024 ** 2:
        raise RuntimeError('Office preview is limited to 256 MiB')
    while not _LOCK.acquire(timeout=0.05):
        if cancel.is_set(): raise RuntimeError('Preview cancelled')
    try:
        if cancel.is_set(): raise RuntimeError('Preview cancelled')
        if valid_pdf(target): return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.convert-', dir=target.parent) as folder:
            output = Path(folder)
            command = [binary, '--headless', '--norestore',
                       '-env:UserInstallation=' + (output / 'profile').as_uri(),
                       '--convert-to', 'pdf', '--outdir', str(output), str(source)]
            # Private process group/profile: cancellation cannot close the user's Office session.
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=os.name == 'posix')
            deadline = time.monotonic() + TIMEOUT
            try:
                while process.poll() is None:
                    if cancel.wait(0.05): raise RuntimeError('Preview cancelled')
                    if time.monotonic() >= deadline: raise RuntimeError('LibreOffice preview timed out')
                if cancel.is_set(): raise RuntimeError('Preview cancelled')
                pdf = output / (source.stem + '.pdf')
                if process.returncode != 0 or not valid_pdf(pdf):
                    raise RuntimeError('LibreOffice could not convert this document')
                if cache_path(source) != target:
                    raise RuntimeError('Document changed during preview; select it again')
                os.replace(pdf, target)
            finally:
                stop_process(process)
        prune()
        return target
    finally:
        _LOCK.release()
