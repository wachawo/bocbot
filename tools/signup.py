#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end signup automation: prepare .env, generate keys, register on
the Battle of Code REST API.

What it does, in order:

  1. Ensure .env exists (copies .env.example if absent).
  2. Read USERNAME from .env and prompt to confirm (Enter to accept,
     or type a new value).
  3. Refuse to proceed while USERNAME == "default".
  4. Generate Ed25519 keypair via tools/keygen.py (idempotent).
  5. Prompt the user to push `keys/<username>.pub` to their GitHub fork on
     a branch named exactly like USERNAME (the server fetches from there).
  6. POST /api/auth/signup -> server fetches GitHub key, returns nonce.
  7. Sign nonce with the local private key.
  8. POST /api/auth/signup/verify -> server stores the pubkey under
     USERNAME and signup is complete.
"""

import logging
import os
import shutil
import sys
import traceback
from pathlib import Path

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
import keygen

from dotenv import dotenv_values, load_dotenv, set_key

logger = logging.getLogger(__name__)

REPO_ROOT      = Path(__file__).resolve().parent.parent
ENV_PATH       = REPO_ROOT / ".env"
ENV_EXAMPLE    = REPO_ROOT / ".env.example"
RESERVED_NAMES = {"default", "anon", "anonymous", "admin", "root", ""}


def ensure_env_file() -> None:
    """Copy .env.example -> .env if .env is missing. Refuse without the example."""
    if ENV_PATH.exists():
        return
    if not ENV_EXAMPLE.exists():
        raise FileNotFoundError(
            f"Neither {ENV_PATH} nor {ENV_EXAMPLE} exists — cannot bootstrap"
        )
    shutil.copyfile(ENV_EXAMPLE, ENV_PATH)
    logger.info(f"Created {ENV_PATH} from {ENV_EXAMPLE.name}")


def confirm_username(current: str) -> str:
    """Prompt the user to confirm or override USERNAME. Returns the chosen value."""
    prompt = f"GitHub login [{current}]: " if current else "GitHub login: "
    try:
        choice = input(prompt).strip()
    except EOFError:
        choice = ""
    return choice or current


def post_signup(api_url: str, username: str) -> str:
    """Step 1 of the REST flow. Returns the hex nonce to sign."""
    resp = requests.post(
        f"{api_url}/api/auth/signup",
        json={"username": username},
        timeout=20,
    )
    if resp.status_code != 200:
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}
        raise RuntimeError(f"signup failed (HTTP {resp.status_code}): {payload}")
    data = resp.json()
    if data.get("status") != "challenge" or "nonce" not in data:
        raise RuntimeError(f"signup: unexpected response: {data}")
    return data["nonce"]


def sign_nonce(private_key_path: Path, nonce_hex: str) -> str:
    raw = private_key_path.read_bytes()
    if len(raw) != 32:
        raise ValueError(f"{private_key_path}: expected 32 raw bytes, got {len(raw)}")
    key = Ed25519PrivateKey.from_private_bytes(raw)
    sig = key.sign(bytes.fromhex(nonce_hex))
    return sig.hex()


def post_verify(api_url: str, username: str, sig_hex: str) -> None:
    resp = requests.post(
        f"{api_url}/api/auth/signup/verify",
        json={"username": username, "sig": sig_hex},
        timeout=20,
    )
    if resp.status_code != 200:
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}
        raise RuntimeError(f"verify failed (HTTP {resp.status_code}): {payload}")
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"verify: unexpected response: {data}")


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ensure_env_file()
    load_dotenv(ENV_PATH)
    env = dotenv_values(ENV_PATH)

    current_username = (env.get("USERNAME") or os.environ.get("USERNAME") or "default").strip()
    username = confirm_username(current_username)

    if username.lower() in RESERVED_NAMES:
        logger.error(
            "Refusing USERNAME=%r — it is a placeholder. "
            "Set it to your real GitHub login (1-39 chars, a-z, 0-9, dashes).",
            username,
        )
        return 1

    if username != current_username:
        set_key(str(ENV_PATH), "USERNAME", username, quote_mode="never")
        logger.info(f"USERNAME persisted to {ENV_PATH}")

    auth_host = env.get("BOC_AUTH_HOST", "127.0.0.1")
    auth_port = env.get("BOC_AUTH_PORT", "8000")
    api_url   = f"http://{auth_host}:{auth_port}"

    report = keygen.generate(username)
    logger.info(
        "%s key for %s",
        "Generated NEW" if report["created_new"] else "Reusing existing",
        username,
    )
    logger.info("  private: %s (mode 0600)", report["private_path"])
    logger.info("  public : %s", report["public_path"])

    print()
    print("=" * 70)
    print(f"  Now push the public key to your GitHub fork on branch '{username}':")
    print()
    print(f"    git checkout -b {username}")
    print(f"    git add keys/{username}.pub")
    print( '    git commit -m "register key"')
    print(f"    git push -u origin {username}")
    print()
    print( "  The server will fetch it from:")
    print(f"    https://raw.githubusercontent.com/{username}/bocbot/{username}/keys/{username}.pub")
    print("=" * 70)
    try:
        input("Press Enter when the public key is pushed (Ctrl-C to abort)…  ")
    except KeyboardInterrupt:
        print()
        logger.info("Aborted by user")
        return 130

    logger.info(f"POST {api_url}/api/auth/signup  username={username}")
    try:
        nonce = post_signup(api_url, username)
    except Exception as exc:
        logger.error(f"signup failed: {type(exc).__name__}: {exc}")
        return 2
    logger.info(f"Received challenge nonce: {nonce}")

    try:
        sig = sign_nonce(Path(report["private_path"]), nonce)
    except Exception as exc:
        logger.error(f"sign failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 3

    logger.info(f"POST {api_url}/api/auth/signup/verify")
    try:
        post_verify(api_url, username, sig)
    except Exception as exc:
        logger.error(f"verify failed: {type(exc).__name__}: {exc}")
        return 4

    print()
    logger.info("✓ Signed up successfully. You can now run python3 client/client.py or python3 bot.py.")
    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.error(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
