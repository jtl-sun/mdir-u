"""Thread-safe, UI-agnostic progress reporting shared by file operations.

The same contract is used for copying, moving, deleting, archives, and search.
An unknown total stays unknown (not a fabricated percentage).
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock
from time import monotonic, sleep
from typing import Callable


class OperationCancelled(Exception):
    """A cooperative cancellation; callers must clean up partial outputs."""


@dataclass(frozen=True)
class ProgressSnapshot:
    operation: str
    current_name: str = ""
    current_bytes: int = 0
    current_total: int = 0
    bytes_done: int = 0
    total_bytes: int | None = None
    items_done: int = 0
    total_items: int | None = None
    found: int = 0
    bytes_per_second: float = 0.0
    items_per_second: float = 0.0
    elapsed: float = 0.0
    eta_seconds: float | None = None
    state: str = "running"

    @property
    def current_percent(self) -> float | None:
        if self.current_total <= 0:
            return None
        return min(100.0, self.current_bytes * 100.0 / self.current_total)

    @property
    def overall_percent(self) -> float | None:
        if self.total_bytes is not None and self.total_bytes > 0:
            return min(100.0, self.bytes_done * 100.0 / self.total_bytes)
        if self.total_items is not None and self.total_items > 0:
            return min(100.0, self.items_done * 100.0 / self.total_items)
        return None


class ProgressTracker:
    """Common progress state with throttled immutable snapshots.

    pause_event is set while paused. Both events are checked between chunks;
    OS-managed operations such as recycling a directory remain non-interruptible.
    """
    def __init__(
        self,
        operation: str,
        *,
        total_items: int | None = None,
        total_bytes: int | None = None,
        cancel_event: Event | None = None,
        pause_event: Event | None = None,
        callback: Callable[[ProgressSnapshot], None] | None = None,
        interval: float = 0.08,
    ) -> None:
        self.operation = operation
        self.cancel_event = cancel_event or Event()
        self.pause_event = pause_event or Event()
        self.callback = callback
        self.interval = max(0.0, interval)
        self._lock = Lock()
        self._started = monotonic()
        self._last_emit = 0.0
        self._current_name = ""
        self._current_done = 0
        self._current_total = 0
        self._bytes_done = 0
        self._total_bytes = total_bytes
        self._items_done = 0
        self._total_items = total_items
        self._found = 0
        self._state = "running"

    def checkpoint(self) -> None:
        while self.pause_event.is_set():
            if self.cancel_event.is_set():
                raise OperationCancelled()
            sleep(0.05)
        if self.cancel_event.is_set():
            raise OperationCancelled()

    def set_totals(
        self, *, items: int | None = None, bytes_total: int | None = None
    ) -> None:
        with self._lock:
            if items is not None:
                self._total_items = max(0, items)
            if bytes_total is not None:
                self._total_bytes = max(0, bytes_total)
        self.publish(force=True)

    def begin_item(self, name: str, size: int = 0) -> None:
        self.checkpoint()
        with self._lock:
            self._current_name = str(name)
            self._current_done = 0
            self._current_total = max(0, int(size))
        self.publish()

    def advance(self, bytes_count: int) -> None:
        self.checkpoint()
        amount = max(0, int(bytes_count))
        with self._lock:
            self._current_done += amount
            self._bytes_done += amount
        self.publish()

    def complete_item(self, *, remaining_bytes: int = 0) -> None:
        with self._lock:
            extra = max(0, int(remaining_bytes))
            self._bytes_done += extra
            self._current_done = self._current_total
            self._items_done += 1
        self.publish(force=True)

    def scan(self, scanned: int, found: int, current: str) -> None:
        with self._lock:
            self._items_done = max(0, int(scanned))
            self._found = max(0, int(found))
            self._current_name = str(current)
        self.publish()

    def finish(self, state: str = "completed") -> None:
        with self._lock:
            self._state = state
        self.publish(force=True)

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            elapsed = max(0.0, monotonic() - self._started)
            rate = self._bytes_done / elapsed if elapsed else 0.0
            item_rate = self._items_done / elapsed if elapsed else 0.0
            remaining = (
                max(0, self._total_bytes - self._bytes_done) / rate
                if self._total_bytes is not None and rate > 0
                else None
            )
            return ProgressSnapshot(
                operation=self.operation,
                current_name=self._current_name,
                current_bytes=self._current_done,
                current_total=self._current_total,
                bytes_done=self._bytes_done,
                total_bytes=self._total_bytes,
                items_done=self._items_done,
                total_items=self._total_items,
                found=self._found,
                bytes_per_second=rate,
                items_per_second=item_rate,
                elapsed=elapsed,
                eta_seconds=remaining,
                state=self._state,
            )

    def publish(self, *, force: bool = False) -> None:
        if self.callback is None:
            return
        with self._lock:
            now = monotonic()
            if not force and now - self._last_emit < self.interval:
                return
            self._last_emit = now
        self.callback(self.snapshot())
