#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Client configuration: loads from .env, overrides via CLI args."""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv, find_dotenv

# override=True so the project's .env wins over any pre-existing OS variable.
# Critical on Windows, where $USERNAME is the OS account name (e.g. "matata")
# and would otherwise mask the GitHub login in .env (e.g. "matata13").
load_dotenv(find_dotenv(), override=True)

TRUE_VALUES = ("1", "true", "yes", "on", "enabled")


@dataclass
class ClientConfig:
    """Container for client-side settings."""

    addr: str
    port: int
    name: str
    log_file: Optional[str]
    log_level: str
    follow_rank: int  # >0 → view-only client following the Nth-rank live player
    # Downsample: pack_x cells horizontally / pack_y cells vertically fold into
    # one terminal char. 0 (default) = auto-fit — renderer picks pack/cell
    # scale so the view fills the available map panel. Set VIEW_PACK_X>0 to
    # force a manual factor.
    view_pack_x: int = 0
    view_pack_y: int = 0
    train_log_file: Optional[str] = None  # legacy field, kept None


def env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


def env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def env_opt_str(key: str) -> Optional[str]:
    val = os.getenv(key)
    if val is None or val == "":
        return None
    return val


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments. CLI overrides env."""
    parser = argparse.ArgumentParser(description="Battle of Code terminal client")
    parser.add_argument("-a", "--addr", type=str, default=None,
                        help="server address")
    parser.add_argument("-p", "--port", type=int, default=None,
                        help="server port")
    parser.add_argument("-n", "--name", type=str, default=None,
                        help="player name")
    parser.add_argument("-l", "--log", type=str, default=None, dest="log_file",
                        help="path to player CSV log (same schema as bot/botai)")
    parser.add_argument("-f", "--follow", type=int, default=0, dest="follow_rank",
                        help="join as a view-only spectator following the Nth-rank "
                             "live player (1..128). WASD is disabled. View-only "
                             "clients get ids >= 1024 and cannot themselves be "
                             "followed.")
    return parser.parse_args()


def load_config() -> ClientConfig:
    """Load config from .env (single env shape across tools/client/bot), CLI overrides."""
    args = parse_args()

    cfg = ClientConfig(
        addr           = env_str("BOC_GAME_HOST", "127.0.0.1"),
        port           = env_int("BOC_GAME_PORT", 5555),
        name           = env_str("USERNAME", ""),
        log_file       = None,
        log_level      = env_str("LOG_LEVEL", "INFO"),
        follow_rank    = 0,
        # 0 = auto-fit; positive = manual fold factor.
        view_pack_x    = max(0, env_int("VIEW_PACK_X", 0)),
        view_pack_y    = max(0, env_int("VIEW_PACK_Y", 0)),
    )

    if args.addr is not None:
        cfg.addr = args.addr
    if args.port is not None:
        cfg.port = args.port
    if args.name is not None:
        cfg.name = args.name
    if args.log_file is not None:
        cfg.log_file = args.log_file
    if args.follow_rank:
        cfg.follow_rank = max(0, min(128, int(args.follow_rank)))

    return cfg


LOGGING = {
    "handlers": [logging.StreamHandler(sys.stderr)],
    "format":   "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s) %(message)s",
    "level":    logging.INFO,
    "datefmt":  "%Y-%m-%d %H:%M:%S",
}


def setup_logging(level_name: str) -> None:
    """Apply logging config; called once at client start. Always to stderr."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    cfg = dict(LOGGING)
    cfg["level"] = level
    logging.basicConfig(**cfg)


def main():
    pass


if __name__ == "__main__":
    main()
