"""Local stderr progress for scan ingest. No telemetry. No network."""

from __future__ import annotations

import sys
import time
from typing import TextIO

# Avoid a line per record on a 25k dump; still frequent enough to look alive.
INTERVAL_SEC = 0.25


def stderr_wants_progress(force: bool, stream: TextIO | None = None) -> bool:
    """True when ``--progress`` is set, or when stderr is a TTY."""
    if force:
        return True
    target = sys.stderr if stream is None else stream
    return bool(target.isatty())


def format_line(records: int, bytes_done: int, bytes_total: int) -> str:
    return (
        f"ingested {records} records, "
        f"{format_bytes(bytes_done)} / {format_bytes(bytes_total)}"
    )


def format_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


class ScanProgress:
    """Write ingest progress to a stream. In-place on a TTY; lines otherwise."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        inplace: bool | None = None,
        interval: float = INTERVAL_SEC,
    ) -> None:
        self._stream = sys.stderr if stream is None else stream
        self._inplace = self._stream.isatty() if inplace is None else inplace
        self._interval = interval
        self._last_t = 0.0
        self._last_line = ""
        self._records = 0
        self._bytes_done = 0
        self._bytes_total = 0
        self._closed = False
        self._seen = False

    def __call__(self, records: int, bytes_done: int, bytes_total: int) -> None:
        self._records = records
        self._bytes_done = bytes_done
        self._bytes_total = bytes_total
        self._seen = True
        self._emit(force=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._seen and not self._last_line:
            return
        self._emit(force=True, final=True)

    def _emit(self, *, force: bool, final: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_t < self._interval:
            return
        self._last_t = now
        line = format_line(self._records, self._bytes_done, self._bytes_total)
        if not final and line == self._last_line:
            return
        if self._inplace:
            pad = max(0, len(self._last_line) - len(line))
            self._stream.write("\r" + line + (" " * pad))
            if final:
                self._stream.write("\n")
            self._stream.flush()
        else:
            self._stream.write(line + "\n")
            self._stream.flush()
        self._last_line = line
