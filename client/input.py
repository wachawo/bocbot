#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-blocking stdin key reader, cross-platform.

POSIX path uses ``termios + tty + select + os.read`` and reads via
``os.read`` (not ``sys.stdin.read``) to bypass the TextIOWrapper buffer.
Otherwise a 3-byte arrow-key sequence (``\\x1b[A``) gets split: the
first call drains all 3 bytes from the kernel into Python's buffer,
returns ``\\x1b``, and the follow-up ``select`` says "no more bytes"
because the OS queue is already empty. The result was a phantom ESC
press every time the user pressed Up/Down/Left/Right, which the main
loop translated to "quit".

Windows path uses ``msvcrt`` — no termios/tty setup needed because
``msvcrt.getwch()`` already reads one character at a time without echo.
Special keys (arrows, function keys) arrive as a two-character sequence
prefixed with ``\\x00`` or ``\\xe0`` (the scan-code prefix); we consume
and ignore them, mirroring the CSI/SS3 swallowing on POSIX.
"""

import logging
import os
import sys
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import msvcrt
else:
    import fcntl
    import select
    import termios
    import tty

VALID_KEYS = ("W", "A", "S", "D", "ESC")


def is_tty() -> bool:
    """Return True if stdin is a TTY (interactive)."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def enter_cbreak() -> Optional[list]:
    """Switch stdin to cbreak (no echo, char-at-a-time) on POSIX.

    Returns saved termios attrs, or None on Windows / non-TTY stdin.
    Windows doesn't need this — ``msvcrt.getwch()`` already reads
    raw characters without echo.
    """
    if IS_WINDOWS or not is_tty():
        return None
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return saved


def restore_terminal(saved: Optional[list]) -> None:
    """Restore stdin termios state (POSIX). No-op on Windows."""
    if IS_WINDOWS or saved is None:
        return
    try:
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    except Exception:
        pass


def drain_raw(fd: int, timeout: float) -> bytes:
    """Wait up to `timeout` for the first byte, then drain everything available
    in a single non-blocking ``os.read``. Bypasses Python's text buffer.

    POSIX only — Windows uses ``_read_keys_windows`` which goes through
    ``msvcrt`` instead of file-descriptor reads.
    """
    if IS_WINDOWS:
        return b""
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


def _read_keys_windows(timeout: float) -> List[str]:
    """Windows path: drain msvcrt keyboard buffer into WSAD + ESC tokens.

    msvcrt.getwch() returns one Unicode char without echo. Special keys
    (arrows, F1-F12, Home, …) come as a two-char sequence: a prefix of
    '\\x00' or '\\xe0' followed by the scan-code char — we read both
    and discard, matching the CSI/SS3 silent-consume on POSIX.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    # Wait for the first keypress up to `timeout`. Poll in 5 ms slices so
    # the main client loop (10 Hz render target) stays responsive without
    # busy-spinning.
    while not msvcrt.kbhit():
        if time.monotonic() >= deadline:
            return []
        time.sleep(0.005)

    keys: List[str] = []
    while msvcrt.kbhit():
        try:
            ch = msvcrt.getwch()
        except Exception:
            break
        if ch in ("\x00", "\xe0"):
            # Scan-code prefix — read and ignore the follow-up byte.
            try:
                msvcrt.getwch()
            except Exception:
                pass
            continue
        if ch == "\x1b":
            keys.append("ESC")
            continue
        up = ch.upper()
        if up in ("W", "A", "S", "D"):
            keys.append(up)
    return keys


def read_keys(timeout: float = 0.0) -> List[str]:
    """Drain available keystrokes from stdin and return uppercase WSAD + ESC.

    Recognised:
      - W/A/S/D       → movement
      - bare Esc      → "ESC" (quit signal)
      - CSI / SS3 seq → silently consumed (arrow keys, function keys, etc.)
      - anything else → ignored
    """
    if not is_tty():
        return []
    if IS_WINDOWS:
        return _read_keys_windows(timeout)
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
