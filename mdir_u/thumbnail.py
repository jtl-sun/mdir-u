"""Bounded thumbnail decoding. This module never creates or touches Tk objects."""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from . import __version__

VERSION = __version__
IMAGE_EXTENSIONS = frozenset({'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.ico'})
SIZES = (96, 120, 144, 168, 192, 216, 240)
MAX_SOURCE_PIXELS = 40_000_000
MAX_PENDING = 128


@dataclass(frozen=True)
class ThumbnailItem:
    path: Path | None
    name: str
    directory: bool
    modified: float = 0
    size: int = 0

    def request_key(self, size: int) -> tuple:
        return (self.path, self.modified, self.size, size)


def grid_columns(width: int, size: int) -> int:
    return max(1, width // (size + 20))


def navigate(index: int, count: int, columns: int, key: str, page_rows: int = 3) -> int:
    delta = {'left': -1, 'right': 1, 'up': -columns, 'down': columns,
             'pageup': -columns * page_rows, 'pagedown': columns * page_rows}
    target = 0 if key == 'home' else count - 1 if key == 'end' else index + delta.get(key, 0)
    return max(0, min(max(0, count - 1), target))


def visible_indices(count: int, columns: int, top: int, height: int, size: int,
                    *, overscan: int = 1) -> range:
    row_height = size + 54
    first = max(0, top // row_height - overscan) * columns
    last = ((top + height + row_height - 1) // row_height + overscan) * columns
    return range(first, min(count, last))


class ThumbnailCache:
    def __init__(self, root: Path | None = None, limit: int = 1024 ** 3):
        self.root = root or Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'mdir-u' / 'thumbnail-cache'
        self.limit = limit
        self._last_cleanup = 0.0
        self._cleanup_lock = threading.Lock()

    def cache_path(self, path: Path, size: int) -> Path:
        stat = path.stat()
        identity = repr((os.path.normcase(str(path.absolute())), stat.st_mtime_ns, stat.st_size, size, 1))
        return self.root / (hashlib.sha256(identity.encode('utf-8')).hexdigest() + '.png')

    def load(self, path: Path, size: int):
        from PIL import Image, ImageOps

        target = self.cache_path(path, size)
        try:
            with Image.open(target) as cached:
                if cached.width > size or cached.height > size:
                    raise ValueError('Invalid thumbnail cache dimensions')
                image = cached.convert('RGB')
            os.utime(target, None)
            return image
        except (OSError, ValueError):
            pass
        with Image.open(path) as source:
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise ValueError('Image exceeds safe thumbnail decode size')
            source.seek(0)
            source.draft('RGB', (size, size))
            oriented = ImageOps.exif_transpose(source)
            try:
                oriented.thumbnail((size, size), Image.Resampling.LANCZOS)
                image = oriented.convert('RGB')
            finally:
                if oriented is not source:
                    oriented.close()
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.root, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                image.save(stream, format='PNG')
            os.replace(temporary, target)
            self.cleanup()
        except OSError:
            pass  # A read-only/full cache must not prevent displaying a thumbnail.
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return image

    def cleanup(self, *, force: bool = False) -> None:
        if not self._cleanup_lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            if not force and now - self._last_cleanup < 60:
                return
            self._last_cleanup = now
            files = []
            for path in self.root.glob('*.png'):
                try:
                    stat = path.stat()
                    files.append((stat.st_mtime_ns, stat.st_size, path))
                except OSError:
                    continue
            total = sum(entry[1] for entry in files)
            for _, size, path in sorted(files):
                if total <= self.limit:
                    break
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    continue
        finally:
            self._cleanup_lock.release()


class ThumbnailLoader:
    """Two daemon decoders with replaceable viewport work and bounded results."""
    def __init__(self, cache: ThumbnailCache | None = None):
        self.cache = cache or ThumbnailCache()
        self.condition = threading.Condition()
        self.wanted: dict[str, tuple] = {}
        self.pending = OrderedDict()
        self.results = OrderedDict()
        self.inflight = set()
        self.stopped = False
        self.threads = [threading.Thread(target=self._run, name=f'mdir-thumbnail-decode-{i}', daemon=True) for i in range(2)]
        for thread in self.threads:
            thread.start()

    def request(self, side: str, keys) -> None:
        with self.condition:
            self.wanted[side] = tuple(keys)[:MAX_PENDING // 2]
            # Rebuild rather than append: rapid scrolling cannot accumulate work.
            wanted = dict.fromkeys(key for batch in self.wanted.values() for key in batch)
            self.pending = OrderedDict((key, None) for key in wanted if key not in self.inflight and key not in self.results)
            self.condition.notify_all()

    def take_results(self):
        with self.condition:
            results, self.results = self.results, OrderedDict()
            return results

    def _run(self) -> None:
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.pending)
                if self.stopped:
                    return
                key, _ = self.pending.popitem(last=False)
                self.inflight.add(key)
            try:
                image = self.cache.load(key[0], key[-1])
            except Exception:
                image = None
            with self.condition:
                self.inflight.discard(key)
                wanted = any(key in batch for batch in self.wanted.values())
                if self.stopped or not wanted:
                    if image is not None:
                        image.close()
                    continue
                self.results[key] = image
                while len(self.results) > MAX_PENDING:
                    _, old = self.results.popitem(last=False)
                    if old is not None:
                        old.close()

    def shutdown(self, timeout: float = 1.0) -> bool:
        with self.condition:
            self.stopped = True
            self.pending.clear()
            self.wanted.clear()
            self.condition.notify_all()
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
        for image in self.take_results().values():
            if image is not None:
                image.close()
        return not any(thread.is_alive() for thread in self.threads)
