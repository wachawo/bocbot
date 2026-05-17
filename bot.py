#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Battle of Code starter bot — single-file, WebSocket + signed-hello auth.

Edit `decide(state)` below. That's the whole game.

Setup (one-time):

    pip install -r requirements.txt          # cryptography + websockets
    python3 tools/signup.py                  # interactive sign-up against the REST API

Then:

    python3 bot.py                           # uses .env (BOC_GAME_HOST / PORT / USERNAME)
"""

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, load_dotenv
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect


# Edit me
# This is the only function you need to change. Everything below it is
# plumbing — connect, auth, reconnect, message dispatch.


def decide(state: Dict[str, Any]) -> str:
    """Pick a direction. Called every server tick (~10 Hz).

    `state` is the latest server snapshot. Useful keys:
        state["me"]      → {"id", "x", "y", "dir", "alive", "trail_len", "area", ...}
        state["view"]    → {"x0", "y0", "w", "h", "zone": [...], "trail": [...]}
        state["players"] → list of nearby players
        state["tick"]    → server tick

    Return one of: "W" (up), "A" (left), "S" (down), "D" (right), or "N"
    (keep current heading). The server rejects 180° turns.

    Default behaviour: always go right. You will hit a wall and die.
    Improve me.
    """
    return "D"


# Plumbing below — WebSocket transport, Ed25519 signed-hello, reconnect


LOGGING = {
    "handlers": [logging.StreamHandler(sys.stderr)],
    "format":   "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s) %(message)s",
    "level":    logging.INFO,
    "datefmt":  "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger("bot")

REPO_ROOT = Path(__file__).resolve().parent
ENV_PATH  = REPO_ROOT / ".env"
KEYS_DIR  = REPO_ROOT / "keys"

load_dotenv(ENV_PATH)
ENV = dotenv_values(ENV_PATH)

DEFAULT_HOST  = ENV.get("BOC_GAME_HOST", "127.0.0.1")
DEFAULT_PORT  = int(ENV.get("BOC_GAME_PORT", "5555"))
USERNAME      = (ENV.get("USERNAME", "") or os.environ.get("USERNAME", "") or "").strip()
RECONNECT_MIN = 1.0
RECONNECT_MAX = 30.0


def load_private_key(username: str) -> Ed25519PrivateKey:
    path = KEYS_DIR / f"{username}.key"
    if not path.exists():
        raise FileNotFoundError(
            f"private key not found: {path}. Run `python3 tools/signup.py` first."
        )
    raw = path.read_bytes()
    if len(raw) != 32:
        raise ValueError(f"{path}: expected 32 raw bytes, got {len(raw)}")
    return Ed25519PrivateKey.from_private_bytes(raw)


def build_hello(username: str, key: Ed25519PrivateKey) -> Dict[str, Any]:
    ts = int(time.time())
    sig = key.sign(f"bocbot:hello:{username}:{ts}".encode("utf-8")).hex()
    return {
        "type":     "hello",
        "username": username,
        "ts":       ts,
        "sig":      sig,
        "is_bot":   True,
        "is_view":  False,
    }


def send_json(ws, obj: Dict[str, Any]) -> None:
    ws.send(json.dumps(obj, ensure_ascii=False))


def run_session(host: str, port: int, username: str, key: Ed25519PrivateKey) -> bool:
    """Single connection lifecycle. Returns True if we should reconnect."""
    ws_url = f"ws://{host}:{port}"
    logger.info(f"Connecting to {ws_url} as {username}")
    # 16 MB: the welcome message ships the player's full owned-cell list,
    # which after a long session can run to several MB of JSON.
    ws = ws_connect(ws_url, max_size=16 * 1024 * 1024, open_timeout=10.0)
    try:
        send_json(ws, build_hello(username, key))
        last_sent_dir: Optional[str] = None
        for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception as exc:
                logger.warning(f"Bad JSON: {type(exc).__name__}: {exc}")
                continue
            mtype = msg.get("type")
            if mtype == "state":
                try:
                    direction = decide(msg)
                except Exception as exc:
                    logger.error(
                        f"decide() crashed: {type(exc).__name__}: {exc}\n"
                        f"{traceback.format_exc()}"
                    )
                    direction = "N"
                if direction in ("W", "A", "S", "D") and direction != last_sent_dir:
                    send_json(ws, {"cmd": "dir", "d": direction})
                    last_sent_dir = direction
            elif mtype == "auth_ok":
                logger.info(f"auth_ok username={msg.get('username', username)}")
            elif mtype == "auth_error":
                logger.error(
                    f"auth_error reason={msg.get('reason')} "
                    f"message={msg.get('message')} detail={msg.get('detail')}"
                )
                return False
            elif mtype == "welcome":
                logger.info(
                    f"Welcome id={msg.get('id')} "
                    f"map={msg.get('map_w')}x{msg.get('map_h')} "
                    f"view={msg.get('view_w')}x{msg.get('view_h')}"
                )
            elif mtype == "died":
                logger.info(
                    f"DIED reason={msg.get('reason')} "
                    f"killer={msg.get('killer')} lost={msg.get('area_lost')}"
                )
                last_sent_dir = None
            elif mtype == "captured":
                logger.info(
                    f"CAPTURED +{msg.get('area_gained')} "
                    f"(trail={msg.get('trail_len')}, total={msg.get('total_area')})"
                )
            elif mtype == "kill":
                logger.info(
                    f"KILL victim={msg.get('victim_name')} via={msg.get('via')}"
                )
            elif mtype == "respawn":
                logger.info(f"RESPAWN at ({msg.get('x')},{msg.get('y')})")
                last_sent_dir = None
            # Unknown / future message types are ignored quietly.
        logger.warning("Server closed the connection")
    except ConnectionClosed as exc:
        logger.warning(f"WebSocket closed: code={exc.code} reason={exc.reason!r}")
        if exc.code == 4401:
            return False  # auth failure — don't retry
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return True


def main() -> int:
    username = USERNAME
    if not username or username.lower() == "default":
        logger.error(
            "USERNAME is not set (or is the placeholder 'default'). "
            "Run `python3 tools/signup.py` first."
        )
        return 1
    try:
        key = load_private_key(username)
    except Exception as exc:
        logger.error(f"load_private_key failed: {type(exc).__name__}: {exc}")
        return 1

    delay = RECONNECT_MIN
    while True:
        try:
            should_retry = run_session(DEFAULT_HOST, DEFAULT_PORT, username, key)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            return 0
        except Exception as exc:
            logger.error(
                f"Session crashed: {type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            )
            should_retry = True
        if not should_retry:
            return 1
        logger.info(f"Reconnecting in {delay:.1f}s")
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            return 0
        delay = min(RECONNECT_MAX, delay * 2)


if __name__ == "__main__":
    sys.exit(main())
