"""Pure, synchronous tailing logic for data/events.jsonl, split out from the
async SSE route so it's unit-testable without any ASGI/asyncio machinery.

Byte offsets throughout (not text-mode seek/tell, which Python only
guarantees round-trips through the same stream's own tell() cookie, not an
arbitrary externally-obtained offset like os.stat().st_size). We read in
binary, decode only the bytes we know are a complete line.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def start_offset(path: Path) -> int:
    """Byte offset to start tailing from: end of file (unix `tail -f`
    semantics). GET /api/events already serves history; the stream is for
    what happens next.
    """
    return path.stat().st_size if path.exists() else 0


def read_new_lines(path: Path, pos: int) -> Tuple[int, List[str]]:
    """Read whatever's been appended to `path` since byte offset `pos`.

    Returns (new_pos, complete non-empty lines). A trailing partial line
    (the writer flushed mid-line) is never returned, and new_pos stays
    before it, so the next call picks up the rest once it's complete.
    """
    if not path.exists():
        return pos, []
    with path.open("rb") as f:
        f.seek(pos)
        data = f.read()
    if not data:
        return pos, []
    nl = data.rfind(b"\n")
    if nl == -1:
        return pos, []  # no complete line yet
    complete = data[: nl + 1]
    new_pos = pos + len(complete)
    text = complete.decode("utf-8", errors="replace")
    lines = [line for line in text.split("\n") if line.strip()]
    return new_pos, lines
