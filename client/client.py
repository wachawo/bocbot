#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Battle of Code terminal client — entry point.

Connects via TCP to the game server, renders the view with the Rich
library (Live + Layout + Panel + Table), reads WSAD/Q from stdin in
cbreak mode, and optionally logs player events and per-action features
for offline training.
"""

import json
import logging
import queue
import signal
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Fail fast with a friendly message if rich / cryptography / websockets are missing.
try:
    import rich  # noqa: F401
    from rich.live import Live
except ImportError:
    sys.stderr.write(
        "rich is required for the client UI. Install it with:\n"
        "    pip install -r requirements.txt\n"
    )
    sys.exit(1)

try:
    from websockets.sync.client import connect as ws_connect
    from websockets.exceptions import ConnectionClosed
except ImportError:
    sys.stderr.write(
        "websockets is required. Install it with:\n"
        "    pip install -r requirements.txt\n"
    )
    sys.exit(1)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    sys.stderr.write(
        "cryptography is required for signed-hello auth. Install it with:\n"
        "    pip install -r requirements.txt\n"
    )
    sys.exit(1)

# Local imports
import config as client_config
import input as input_mod
import logger as logger_mod
import render

logger = logging.getLogger(__name__)

KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"

FRAME_INTERVAL = 1.0 / 10.0  # render at server state rate (10 Hz) — twice that
                             # just re-rendered identical frames and doubled CPU
FLASH_DURATION = 1.5  # seconds


def recv_loop(ws, q: "queue.Queue[Optional[Dict[str, Any]]]") -> None:
    """Read JSON frames from the WebSocket and push parsed dicts to the queue.

    Puts None on disconnect to signal main loop.
    """
    try:
        while True:
            try:
                raw = ws.recv()
            except ConnectionClosed:
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception as exc:
                logger.warning(
                    f"Bad JSON from server: {type(exc).__name__}: {str(exc)}"
                )
                continue
            q.put(msg)
    except Exception as exc:
        logger.error(
            f"recv_loop error: {type(exc).__name__}: {str(exc)}\n"
            f"{traceback.format_exc()}"
        )
    finally:
        q.put(None)


def send_json(ws, payload: Dict[str, Any]) -> None:
    """Send one JSON message over the WebSocket."""
    data = json.dumps(payload, ensure_ascii=False)
    try:
        ws.send(data)
    except Exception as exc:
        logger.warning(f"send_json failed: {type(exc).__name__}: {str(exc)}")
        raise


def load_private_key(username: str) -> Ed25519PrivateKey:
    path = KEYS_DIR / f"{username}.key"
    if not path.exists():
        raise FileNotFoundError(
            f"private key not found: {path}. Run tools/signup.py first."
        )
    raw = path.read_bytes()
    if len(raw) != 32:
        raise ValueError(f"{path}: expected 32 raw bytes, got {len(raw)}")
    return Ed25519PrivateKey.from_private_bytes(raw)


def build_hello(username: str, key: Ed25519PrivateKey, follow_rank: int = 0) -> Dict[str, Any]:
    ts = int(time.time())
    sig = key.sign(f"bocbot:hello:{username}:{ts}".encode("utf-8")).hex()
    return {
        "type":        "hello",
        "username":    username,
        "ts":          ts,
        "sig":         sig,
        "is_view":     follow_rank > 0,
        "is_bot":      False,
        "follow_rank": follow_rank,
    }


def key_to_dir(key: str) -> Optional[str]:
    """Map a key to a direction command (or None)."""
    if key in ("W", "A", "S", "D"):
        return key
    return None


def connect_and_join(
    cfg: client_config.ClientConfig,
) -> Optional[Tuple[Any, "queue.Queue[Optional[Dict[str, Any]]]"]]:
    """Open the game WebSocket, send signed hello, start the recv thread.

    Returns (ws, queue) on success or None if the connect / auth failed.
    Caller is responsible for closing the ws. Reconnect logic in
    `run_session` calls this in a backoff loop.
    """
    if not cfg.name or cfg.name == "default":
        logger.error("USERNAME is not set (or is the placeholder 'default'). Run tools/signup.py first.")
        return None
    try:
        key = load_private_key(cfg.name)
    except Exception as exc:
        logger.error(f"load_private_key failed: {type(exc).__name__}: {str(exc)}")
        return None

    ws_url = f"ws://{cfg.addr}:{cfg.port}"
    try:
        # 16 MB: welcome ships every cell the player owns; a 1024×768 map can
        # produce a multi-MB payload after a big capture session.
        ws = ws_connect(ws_url, max_size=16 * 1024 * 1024, open_timeout=10.0)
    except Exception as exc:
        logger.warning(
            f"Connect to {ws_url} failed: {type(exc).__name__}: {str(exc)}"
        )
        return None
    logger.info(f"Connected to {ws_url}")

    hello = build_hello(cfg.name, key, follow_rank=cfg.follow_rank)
    try:
        send_json(ws, hello)
    except Exception:
        try:
            ws.close()
        except Exception:
            pass
        return None

    msg_q: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
    rx = threading.Thread(target=recv_loop, args=(ws, msg_q), daemon=True)
    rx.start()
    return ws, msg_q


def run_session(cfg: client_config.ClientConfig) -> int:
    """Open connection, run the I/O loop with automatic reconnect.

    The Live render context spans the whole session; on disconnect we
    transparently re-open the WebSocket + recv thread, and the server
    (via signed-hello against the stored pubkey) resumes our paused
    player. The user only sees the connection status flip to
    "reconnecting…" in the footer.
    """
    spectating = cfg.follow_rank > 0
    res = connect_and_join(cfg)
    if res is None:
        return 1
    ws, msg_q = res

    # Double-Ctrl+C quit: first SIGINT only arms a 2-second deadline. The
    # second one within the window raises KeyboardInterrupt so the regular
    # cleanup path runs. Single Esc / Q in the input loop also quits cleanly.
    DOUBLE_INTR_SEC = 2.0
    intr_deadline = [0.0]

    def sigint_handler(signum, frame):
        t = time.monotonic()
        if t < intr_deadline[0]:
            raise KeyboardInterrupt()
        intr_deadline[0] = t + DOUBLE_INTR_SEC
        logger.info("Ctrl+C — press again within 2s to quit (Esc / Q also work)")

    try:
        signal.signal(signal.SIGINT, sigint_handler)
    except Exception:
        pass

    # Terminal raw mode (cbreak)
    saved_termios = input_mod.enter_cbreak()

    # State snapshots for renderer / train log
    welcome: Dict[str, Any] = {}
    last_me: Dict[str, Any] = {"id": 0, "x": 0, "y": 0, "dir": "N",
                                "alive": True, "trail_len": 0, "area": 0,
                                "score": 0, "deaths": 0, "kills": 0}
    last_view: Dict[str, Any] = {"x0": 0, "y0": 0, "w": 0, "h": 0,
                                  "zone": [], "trail": []}
    last_players: List[Dict[str, Any]] = []
    last_scores: List[Dict[str, Any]] = []
    last_tick: int = 0
    last_uptime: int = 0
    have_state: bool = False
    flash: Optional[Tuple[str, float]] = None
    render_state = render.RenderState()
    memory = render.MemoryMap()
    connection: str = "connected"
    # Round-trip latency tracked via periodic PING/PONG. Set on first
    # pong response; updated every PING_INTERVAL_SEC. -1 = unknown yet.
    latency_ms: int = -1
    PING_INTERVAL_SEC = 2.0
    next_ping_at: float = 0.0
    last_ping_t: float = 0.0
    RECONNECT_MIN = 0.5
    RECONNECT_MAX = 5.0
    reconnect_delay = RECONNECT_MIN
    reconnect_at = 0.0  # monotonic deadline; 0 = no pending reconnect

    # Player logger (optional)
    handicap_default = 3
    plog: Optional[logger_mod.PlayerLogger] = None
    if cfg.log_file or cfg.train_log_file:
        plog = logger_mod.PlayerLogger(
            events_path=cfg.log_file,
            train_path=cfg.train_log_file,
            actor_name=cfg.name,
            handicap=handicap_default,
        )

    exit_code = 0
    last_render = 0.0
    last_rendered_tick: int = -1
    pending_render: bool = True   # initial frame
    running = True

    console = render.make_console()

    def make_renderable():
        return render.build_layout(
            me=last_me,
            view=last_view,
            players=last_players,
            scores=last_scores,
            events=render_state.visible_events(),
            flash=flash,
            name=cfg.name,
            console_width=console.size.width,
            console_height=console.size.height,
            pack_x=cfg.view_pack_x,
            pack_y=cfg.view_pack_y,
            server_uptime_sec=last_uptime,
            connection=connection,
            map_w=int(welcome.get("map_w", 0)),
            map_h=int(welcome.get("map_h", 0)),
            memory=memory,
            latency_ms=latency_ms,
        )

    try:
        # auto_refresh=False — Rich won't redraw on a timer. We push
        # `live.update(...)` only when a new server state arrives. With
        # state arriving at 10 Hz this naturally caps redraws at 10 Hz
        # without the cost of "render again with identical content" pings.
        with Live(
            make_renderable(),
            console=console,
            screen=True,
            transient=False,
            auto_refresh=False,
        ) as live:
            while running:
                # Drain server messages (non-blocking). Any processed message
                # marks the layout dirty so the next throttled render fires.
                try:
                    while True:
                        msg = msg_q.get_nowait()
                        pending_render = True
                        if msg is None:
                            logger.warning("Server closed connection — reconnecting")
                            connection = "reconnecting"
                            try:
                                ws.close()
                            except Exception:
                                pass
                            reconnect_at = time.monotonic() + reconnect_delay
                            # Drop queue/ws; outer loop will recreate them.
                            msg_q = queue.Queue()
                            ws = None  # type: ignore[assignment]
                            break
                        mtype = msg.get("type")
                        if mtype == "auth_ok":
                            logger.info(f"auth_ok username={msg.get('username', cfg.name)}")
                        elif mtype == "auth_error":
                            reason = msg.get("reason", "unknown")
                            message = msg.get("message", "")
                            logger.error(
                                f"auth_error reason={reason} message={message}"
                            )
                            running = False
                            exit_code = 1
                            break
                        elif mtype == "welcome":
                            welcome = msg
                            if plog is not None:
                                plog.handicap = int(msg.get("handicap", handicap_default))
                            mw = int(msg.get("map_w", 0))
                            mh = int(msg.get("map_h", 0))
                            if mw > 0 and mh > 0 and (memory.map_w != mw or memory.map_h != mh):
                                memory.resize(mw, mh)
                            logger.info(
                                f"Welcome id={msg.get('id')} map={mw}x{mh} "
                                f"view={msg.get('view_w')}x{msg.get('view_h')} "
                                f"handicap={msg.get('handicap')}"
                            )
                        elif mtype == "state":
                            last_me = msg.get("me", last_me) or last_me
                            last_view = msg.get("view", last_view) or last_view
                            if memory.map_w > 0:
                                # Apply fog FIRST (wider, filtered: own
                                # trail only, no enemy trail), then view
                                # OVERWRITES for the cells in the live
                                # view rectangle (full trail incl. enemy).
                                fog = msg.get("fog")
                                if fog:
                                    memory.update_from_fog(fog)
                                memory.update_from_view(last_view)
                            last_players = msg.get("players", []) or []
                            # scores arrive every ~5 s (server rate-limits the
                            # heavy dashboard array). When the field is absent
                            # keep the previously cached list — don't wipe it.
                            if "scores" in msg:
                                last_scores = msg.get("scores", []) or []
                            last_tick = int(msg.get("tick", last_tick))
                            last_uptime = int(msg.get("uptime_sec", last_uptime))
                            have_state = True
                            pending_render = True
                        elif mtype == "died":
                            reason = str(msg.get("reason", "?"))
                            killer = int(msg.get("killer", 0))
                            area_lost = int(msg.get("area_lost", 0))
                            text = f"DIED {reason} (killer={killer}, lost={area_lost})"
                            flash = (text, time.monotonic() + FLASH_DURATION)
                            render_state.push_event(text)
                            if plog is not None:
                                trail_at_death = int(last_me.get("trail_len", 0) or 0)
                                plog.log_death(reason, killer, area_lost,
                                               trail_len_at_death=trail_at_death)
                        elif mtype == "captured":
                            gain = int(msg.get("area_gained", 0))
                            tl = int(msg.get("trail_len", 0))
                            total = int(msg.get("total_area", 0))
                            text = f"CAPTURED +{gain} (trail={tl}, total={total})"
                            flash = (text, time.monotonic() + FLASH_DURATION)
                            render_state.push_event(text)
                            # Server has folded our trail + interior into our
                            # zone; sync client memory using the cell delta the
                            # server attached so off-screen cells redraw as
                            # zone fill instead of stale "·" / wrong owner /
                            # blank.
                            my_pid = int(last_me.get("id", 0))
                            if my_pid > 0:
                                memory.commit_capture(my_pid, msg.get("cells"))
                            if plog is not None:
                                plog.log_capture(gain, tl, total)
                        elif mtype == "kill":
                            victim = int(msg.get("victim", 0))
                            vname = str(msg.get("victim_name", "?"))
                            via = str(msg.get("via", "?"))
                            text = f"KILL {vname} (#{victim}) via {via}"
                            flash = (text, time.monotonic() + FLASH_DURATION)
                            render_state.push_event(text)
                            if plog is not None:
                                plog.log_kill(victim, vname, via)
                        elif mtype == "respawn":
                            rx_x = int(msg.get("x", 0))
                            ry_y = int(msg.get("y", 0))
                            text = f"RESPAWN at ({rx_x},{ry_y})"
                            flash = (text, time.monotonic() + FLASH_DURATION)
                            render_state.push_event(text)
                            if plog is not None:
                                plog.log_respawn(rx_x, ry_y)
                        elif mtype == "pong":
                            # Server echoes the client-side t we sent.
                            sent_t = float(msg.get("t", 0) or 0)
                            if sent_t > 0:
                                latency_ms = max(0, int((time.monotonic() - sent_t) * 1000))
                        else:
                            # Unknown / future event types — ignore quietly
                            pass
                except queue.Empty:
                    pass

                if not running:
                    break

                # Reconnect tick: if the WebSocket is down, try to re-establish
                # after the backoff delay. The signed-hello against the
                # server-stored pubkey resumes the paused player rather than
                # spawn a fresh one.
                if connection == "reconnecting" and time.monotonic() >= reconnect_at:
                    res = connect_and_join(cfg)
                    if res is None:
                        reconnect_delay = min(RECONNECT_MAX, reconnect_delay * 2)
                        reconnect_at = time.monotonic() + reconnect_delay
                    else:
                        ws, msg_q = res
                        connection = "connected"
                        reconnect_delay = RECONNECT_MIN
                        reconnect_at = 0.0
                        latency_ms = -1
                        logger.info("Reconnected")

                # Periodic ping: server echoes our monotonic timestamp; the
                # pong handler converts the delta into ms and the header
                # displays "● Online (Nms)".
                if ws is not None and connection == "connected":
                    now_t = time.monotonic()
                    if now_t >= next_ping_at:
                        try:
                            send_json(ws, {"cmd": "ping", "t": now_t})
                            last_ping_t = now_t
                        except Exception:
                            pass
                        next_ping_at = now_t + PING_INTERVAL_SEC

                # Keyboard input. Quit: ESC (single) or two Ctrl+C presses
                # within DOUBLE_INTR_SEC. WASD is ignored in spectator mode.
                keys = input_mod.read_keys(timeout=0.0)
                for key in keys:
                    if key == "ESC":
                        if ws is not None:
                            try:
                                send_json(ws, {"cmd": "quit"})
                            except Exception:
                                pass
                        running = False
                        break
                    if spectating:
                        continue  # WASD ignored for view-only clients
                    d = key_to_dir(key)
                    if d is None:
                        continue
                    if ws is None:
                        continue  # disconnected; key is ignored while reconnecting
                    dir_before = str(last_me.get("dir", "N"))
                    try:
                        send_json(ws, {"cmd": "dir", "d": d})
                    except Exception:
                        connection = "reconnecting"
                        try:
                            ws.close()
                        except Exception:
                            pass
                        ws = None  # type: ignore[assignment]
                        reconnect_at = time.monotonic() + reconnect_delay
                        break
                    if plog is not None:
                        plog.log_player_input(
                            key=d,
                            dir_before=dir_before,
                            tick=last_tick,
                            x=int(last_me.get("x", 0)),
                            y=int(last_me.get("y", 0)),
                        )
                        if have_state:
                            plog.log_train_step(
                                tick=last_tick,
                                action=d,
                                me=last_me,
                                view=last_view,
                                players=last_players,
                            )

                # Refresh Rich layout — only when state or events actually
                # changed AND we're past the throttle. With auto_refresh=False
                # this is the ONLY path that emits ANSI to the terminal.
                now = time.monotonic()
                # Force a refresh if a transient flash is showing/expiring
                # so the panel doesn't get stuck with stale text.
                flash_live = flash is not None and flash[1] > now
                if (pending_render or flash_live) and have_state \
                        and (now - last_render) >= FRAME_INTERVAL:
                    try:
                        live.update(make_renderable(), refresh=True)
                    except Exception as exc:
                        logger.error(
                            f"render error: {type(exc).__name__}: {str(exc)}\n"
                            f"{traceback.format_exc()}"
                        )
                    last_render = now
                    pending_render = False
                    last_rendered_tick = last_tick

                # Tiny sleep to avoid busy spin
                time.sleep(0.02)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        if ws is not None:
            try:
                send_json(ws, {"cmd": "quit"})
            except Exception:
                pass
    except Exception as exc:
        logger.error(
            f"Session error: {type(exc).__name__}: {str(exc)}\n"
            f"{traceback.format_exc()}"
        )
        exit_code = 1
    finally:
        input_mod.restore_terminal(saved_termios)
        if plog is not None:
            plog.close()
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    return exit_code


def install_signal_handlers() -> None:
    """Make sure SIGTERM behaves like KeyboardInterrupt so cleanup runs."""
    def handler(signum, frame):
        raise KeyboardInterrupt()
    try:
        signal.signal(signal.SIGTERM, handler)
    except Exception:
        pass


def main() -> None:
    cfg = client_config.load_config()
    client_config.setup_logging(cfg.log_level)
    install_signal_handlers()
    code = run_session(cfg)
    sys.exit(code)


if __name__ == "__main__":
    main()
