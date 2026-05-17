#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke-test: connect to the game WebSocket with a signed hello, send
PING, expect PONG. If both work, the full auth chain is healthy.

Run after ``tools/signup.py``:

    python3 tools/login.py
"""

import asyncio
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Local imports
from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KEYS_DIR  = REPO_ROOT / "keys"
ENV_PATH  = REPO_ROOT / ".env"


def make_hello(username: str, priv_path: Path) -> dict:
    raw = priv_path.read_bytes()
    if len(raw) != 32:
        raise ValueError(f"{priv_path}: expected 32 raw bytes, got {len(raw)}")
    key = Ed25519PrivateKey.from_private_bytes(raw)
    ts = int(time.time())
    message = f"bocbot:hello:{username}:{ts}".encode("utf-8")
    sig = key.sign(message).hex()
    return {"type": "hello", "username": username, "ts": ts, "sig": sig}


async def smoke_test(ws_url: str, hello: dict, timeout: float = 10.0) -> int:
    async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps(hello))
        # Expect auth_ok + welcome, then ping/pong.
        deadline = time.monotonic() + timeout
        got_auth_ok = False
        got_welcome = False
        while time.monotonic() < deadline and not (got_auth_ok and got_welcome):
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "auth_error":
                logger.error(f"auth_error: {msg}")
                return 1
            if mtype == "auth_ok":
                got_auth_ok = True
                logger.info(f"auth_ok username={msg.get('username')}")
            elif mtype == "welcome":
                got_welcome = True
                logger.info(
                    f"welcome id={msg.get('id')} map={msg.get('map_w')}x{msg.get('map_h')} "
                    f"view={msg.get('view_w')}x{msg.get('view_h')}"
                )
        if not (got_auth_ok and got_welcome):
            logger.error("Did not receive both auth_ok and welcome in time")
            return 2

        ping_t = int(time.time() * 1000)
        await ws.send(json.dumps({"cmd": "ping", "t": ping_t}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if msg.get("type") == "pong":
                rtt = int(time.time() * 1000) - ping_t
                logger.info(f"pong rtt={rtt}ms server_t={msg.get('server_t'):.3f}")
                return 0
            # State frames may arrive in between; ignore.
    return 3


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(ENV_PATH)
    env = dotenv_values(ENV_PATH)

    username = (env.get("USERNAME") or os.environ.get("USERNAME") or "").strip()
    if not username or username.lower() == "default":
        logger.error("USERNAME is not set (or is the placeholder 'default'). Run tools/signup.py first.")
        return 1

    priv_path = KEYS_DIR / f"{username}.key"
    if not priv_path.exists():
        logger.error(f"Private key not found: {priv_path}. Run tools/signup.py first.")
        return 1

    host = env.get("BOC_GAME_HOST", "127.0.0.1")
    port = env.get("BOC_GAME_PORT", "5555")
    ws_url = f"ws://{host}:{port}"

    try:
        hello = make_hello(username, priv_path)
    except Exception as exc:
        logger.error(f"make_hello: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 2

    logger.info(f"Connecting to {ws_url} as {username}")
    try:
        return asyncio.run(smoke_test(ws_url, hello))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except Exception as exc:
        logger.error(f"login failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 4


if __name__ == "__main__":
    sys.exit(main())
