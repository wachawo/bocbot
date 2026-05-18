#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-blocking stdin key reader using termios + tty + select.

Reads via ``os.read`` (not ``sys.stdin.read``) to bypass the TextIOWrapper
buffer. Otherwise a 3-byte arrow-key sequence (``\\x1b[A``) gets split: the
first call drains all 3 bytes from the kernel into Python's buffer, returns
``\\x1b``, and the follow-up ``select`` says "no more bytes" because the OS
queue is already empty. The result was a phantom ESC press every time the
user pressed Up/Down/Left/Right, which the main loop translated to "quit".
"""

import fcntl
import logging
import os
import select
import sys
import termios
import tty
from typing import List, Optional

logger = logging.getLogger(__name__)

VALID_KEYS = ("W", "A", "S", "D", "ESC")


def is_tty() -> bool:
    """Return True if stdin is a TTY (interactive)."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def enter_cbreak() -> Optional[list]:
    """Switch stdin to cbreak (no echo, char-at-a-time).

    Returns saved termios attrs, or None if stdin is not a TTY.
    """
    if not is_tty():
        return None
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return saved


def restore_terminal(saved: Optional[list]) -> None:
    """Restore stdin termios state."""
    if saved is None:
        return
    try:
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    except Exception:
        pass


def drain_raw(fd: int, timeout: float) -> bytes:
    """Wait up to `timeout` for the first byte, then drain everything available
    in a single non-blocking ``os.read``. Bypasses Python's text buffer."""
    rlist, _, _ = select.select([fd], [], [], timeout)
    if not rlist:
        return b""
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        try:
            return os.read(fd, 4096)
        except BlockingIOError:
            return b""
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def read_keys(timeout: float = 0.0) -> List[str]:
    """Drain available bytes from stdin and return uppercase WSAD + ESC.

    Recognised:
      - W/A/S/D       → movement
      - bare Esc      → "ESC" (quit signal)
      - CSI / SS3 seq → silently consumed (arrow keys, function keys, etc.)
      - anything else → ignored
    """
    if not is_tty():
        return []
    raw = drain_raw(sys.stdin.fileno(), timeout)
    keys: List[str] = []
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0x1b:  # ESC byte
            # If immediately followed by '[' (CSI) or 'O' (SS3) it's an
            # escape sequence (arrow / Fn / etc) — eat to the "final byte"
            # which for CSI is anything in 0x40..0x7e.
            if i + 1 < len(raw) and raw[i + 1] in (0x5b, 0x4f):  # '[' or 'O'
                j = i + 2
                while j < len(raw) and not (0x40 <= raw[j] <= 0x7e):
                    j += 1
                i = j + 1
                continue
            keys.append("ESC")
            i += 1
            continue
        try:
            ch = chr(b).upper()
        except Exception:
            ch = ""
        if ch in ("W", "A", "S", "D"):
            keys.append(ch)
        i += 1
    return keys


def main():
    pass


if __name__ == "__main__":
    main()
