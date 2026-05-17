#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate an Ed25519 keypair for Battle of Code.

Both halves live under ``keys/``:

    keys/<username>.key   - 32 raw private bytes, mode 0600, git-ignored.
    keys/<username>.pub   - hex-encoded public key, commit-able. Push it on
                            the branch named after your GitHub login so the
                            server can fetch it.

Run as a module from anywhere in the repo:

    python3 tools/keygen.py <username>
    python3 tools/keygen.py            # picks up USERNAME from .env

Designed to be imported by ``tools/signup.py``. Idempotent: if the private
key already exists, the public key is regenerated from it.
"""

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KEYS_DIR  = REPO_ROOT / "keys"


def keypair_paths(username: str) -> Tuple[Path, Path]:
    return KEYS_DIR / f"{username}.key", KEYS_DIR / f"{username}.pub"


def write_private(private_key: Ed25519PrivateKey, path: Path) -> None:
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    os.chmod(path, 0o600)


def write_public(private_key: Ed25519PrivateKey, path: Path, username: str) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pubkey_hex = raw.hex()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# bocbot key for {username}\n{pubkey_hex}\n", encoding="utf-8")
    return pubkey_hex


def load_or_generate(username: str) -> Tuple[Ed25519PrivateKey, Path, Path, bool]:
    """Return (key, priv_path, pub_path, created_new)."""
    priv_path, pub_path = keypair_paths(username)
    if priv_path.exists():
        raw = priv_path.read_bytes()
        if len(raw) != 32:
            raise ValueError(
                f"{priv_path}: expected 32 raw bytes, got {len(raw)} — refusing to overwrite. "
                "Delete the file manually if you want to regenerate."
            )
        return Ed25519PrivateKey.from_private_bytes(raw), priv_path, pub_path, False
    key = Ed25519PrivateKey.generate()
    write_private(key, priv_path)
    return key, priv_path, pub_path, True


def generate(username: str) -> dict:
    """Library entry point. Returns a small report dict."""
    key, priv_path, pub_path, created_new = load_or_generate(username)
    pubkey_hex = write_public(key, pub_path, username)
    return {
        "username":     username,
        "private_path": str(priv_path),
        "public_path":  str(pub_path),
        "pubkey_hex":   pubkey_hex,
        "created_new":  created_new,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Generate Ed25519 keypair for bocbot")
    parser.add_argument(
        "username",
        nargs="?",
        default=os.environ.get("USERNAME") or "",
        help="GitHub login (default: $USERNAME from environment or .env)",
    )
    args = parser.parse_args()
    if not args.username or args.username == "default":
        logger.error(
            "username is required (got %r). Pass it as an argument or set USERNAME in .env.",
            args.username,
        )
        return 1
    try:
        report = generate(args.username)
    except Exception as exc:
        logger.error(f"keygen failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return 2
    logger.info(
        "%s key for %s",
        "Generated NEW" if report["created_new"] else "Reusing existing",
        report["username"],
    )
    logger.info("  private: %s (mode 0600)", report["private_path"])
    logger.info("  public : %s", report["public_path"])
    logger.info("  pubkey : %s", report["pubkey_hex"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
