#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional CSV logging of player events and per-tick training features.

Uses the exact same schema as bot/logger.py and botai/logger.py so botcouch
can ingest a mixed corpus of bots and humans through one input format.
Distinguished only by `source="human"` and `ai_state=""`.
"""

import csv
import json
import logging
import os
import time
import traceback
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_NEUTRAL = "neutral"

COLUMNS = [
    "t", "episode_id", "kind", "event", "action", "ai_state", "tick_outcome",
    "x", "y", "dir", "trail_len", "own_area", "alive_seconds",
    "dist_to_home", "nearest_enemy_dist", "nearest_enemy_dx", "nearest_enemy_dy",
    "nearest_enemy_trail_dist", "n_enemies_visible",
    "source", "actor_name",
    "cfg_vision_radius", "cfg_max_home_distance", "cfg_max_trail_len", "cfg_safety_factor",
    "extra",
]


def open_append_csv(path: Optional[str]):
    if not path:
        return None, None
    try:
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        is_new = not os.path.isfile(path) or os.path.getsize(path) == 0
        fp = open(path, "a", encoding="utf-8", newline="", buffering=1)
        writer = csv.DictWriter(fp, fieldnames=COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        return fp, writer
    except Exception as exc:
        logger.error(
            f"Failed to open CSV log file {path}: "
            f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        )
        return None, None


class PlayerLogger:
    """Writes a single CSV with both per-tick rows and events (source=human)."""

    def __init__(
        self,
        events_path: Optional[str],
        train_path: Optional[str],
        actor_name: str,
        handicap: int,
    ) -> None:
        log_path = events_path or train_path
        self.log_path = log_path
        self.actor_name = actor_name
        self.handicap = handicap
        self.fp, self.writer = open_append_csv(log_path)
        self.tick_buffer: List[Dict[str, Any]] = []

        self.episode_id: int = 0
        self.session_start_t: float = time.time()
        self.episode_start_t: float = self.session_start_t
        self.captures_count: int = 0
        self.captured_area_total: int = 0
        self.captured_length_total: int = 0
        self.kills: int = 0
        self.deaths: int = 0
        self.max_area: int = 0

        self.capture_fails: int = 0
        self.wasted_trail_total: int = 0
        self.round_capture_fails: int = 0
        self.round_wasted_trail_total: int = 0

    def cfg_snapshot(self) -> Dict[str, Any]:
        return {
            "vision_radius":   self.handicap,
            "max_explore_dist": None,
            "max_trail_len":    None,
            "safety_factor":    None,
        }

    def build_row(
        self, *,
        kind: str,
        event: str = "",
        obs: Optional[Dict[str, Any]] = None,
        action: str = "",
        ai_state: str = "",
        tick_outcome: str = "",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        obs = obs or {}
        extras = extra_fields or {}
        cfg = self.cfg_snapshot()
        return {
            "t":              round(time.time(), 3),
            "episode_id":     self.episode_id,
            "kind":           kind,
            "event":          event,
            "action":         action,
            "ai_state":       ai_state,
            "tick_outcome":   tick_outcome,
            "x":              obs.get("x", ""),
            "y":              obs.get("y", ""),
            "dir":            obs.get("dir", ""),
            "trail_len":      obs.get("trail_len", ""),
            "own_area":       obs.get("own_area", ""),
            "alive_seconds":  obs.get("alive_seconds", ""),
            "dist_to_home":   obs.get("dist_to_home", ""),
            "nearest_enemy_dist":       obs.get("nearest_enemy_dist", ""),
            "nearest_enemy_dx":         obs.get("nearest_enemy_dx", ""),
            "nearest_enemy_dy":         obs.get("nearest_enemy_dy", ""),
            "nearest_enemy_trail_dist": obs.get("nearest_enemy_trail_dist", ""),
            "n_enemies_visible":        obs.get("n_enemies_visible", ""),
            "source":         "human",
            "actor_name":     self.actor_name,
            "cfg_vision_radius":    cfg["vision_radius"],
            "cfg_max_home_distance": "",
            "cfg_max_trail_len":    "",
            "cfg_safety_factor":    "",
            "extra":          json.dumps(extras, ensure_ascii=False) if extras else "",
        }

    def write_event(self, event: str, **fields: Any) -> None:
        if self.writer is None:
            return
        try:
            self.writer.writerow(self.build_row(kind="event", event=event, extra_fields=fields))
        except Exception as exc:
            logger.error(
                f"write_event failed: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
            )

    def flush_buffer(self, outcome: str) -> None:
        if self.writer is None:
            self.tick_buffer = []
            return
        try:
            for rec in self.tick_buffer:
                obs = rec.get("obs") or {}
                trail_len = int(obs.get("trail_len", 0) or 0)
                final = OUTCOME_NEUTRAL if (outcome != OUTCOME_NEUTRAL and trail_len == 0) else outcome
                self.writer.writerow(self.build_row(
                    kind="tick",
                    obs=obs,
                    action=rec.get("action", ""),
                    ai_state="",
                    tick_outcome=final,
                ))
        except Exception as exc:
            logger.error(
                f"flush_buffer failed: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
            )
        finally:
            self.tick_buffer = []

    def mark_milestone(self, kind: str) -> None:
        if kind == "capture":
            self.flush_buffer(OUTCOME_SUCCESS)
        elif kind in ("capture_fail", "death"):
            self.flush_buffer(OUTCOME_FAILURE)
        else:
            self.flush_buffer(OUTCOME_NEUTRAL)

    def log_player_input(self, key: str, dir_before: str, tick: int, x: int, y: int) -> None:
        self.write_event(
            "player_input", key=key, dir_before=dir_before, tick=tick, x=x, y=y,
        )

    def log_train_step(
        self, tick: int, action: str,
        me: Dict[str, Any],
        view: Optional[Dict[str, Any]],
        players: List[Dict[str, Any]],
    ) -> None:
        now = time.time()
        x = int(me.get("x", 0))
        y = int(me.get("y", 0))
        trail_len = int(me.get("trail_len", 0))
        own_area = int(me.get("area", 0))
        dir_cur = str(me.get("dir", "N"))
        alive_seconds = max(0.0, now - self.episode_start_t)
        my_id = me.get("id")

        nearest_dist: Optional[float] = None
        nearest_dx = 0
        nearest_dy = 0
        n_visible = 0
        for p in players:
            if p.get("id") == my_id:
                continue
            n_visible += 1
            dx = int(p.get("x", 0)) - x
            dy = int(p.get("y", 0)) - y
            d = (dx * dx + dy * dy) ** 0.5
            if nearest_dist is None or d < nearest_dist:
                nearest_dist = d
                nearest_dx = dx
                nearest_dy = dy

        obs = {
            "x": x, "y": y, "dir": dir_cur,
            "trail_len": trail_len, "own_area": own_area,
            "alive_seconds": round(alive_seconds, 3),
            "dist_to_home": "",
            "nearest_enemy_dist": round(nearest_dist, 3) if nearest_dist is not None else "",
            "nearest_enemy_dx": nearest_dx, "nearest_enemy_dy": nearest_dy,
            "nearest_enemy_trail_dist": "",
            "n_enemies_visible": n_visible,
        }
        self.tick_buffer.append({"action": action, "obs": obs})

    def log_capture(self, area_gained: int, trail_len: int, total_area: int) -> None:
        self.captures_count += 1
        self.captured_area_total += int(area_gained)
        self.captured_length_total += int(trail_len)
        if total_area > self.max_area:
            self.max_area = int(total_area)
        self.write_event(
            "capture",
            area_gained=int(area_gained), trail_len=int(trail_len),
            total_area=int(total_area),
        )
        self.mark_milestone("capture")

    def log_death(self, reason: str, killer: int, area_lost: int,
                  trail_len_at_death: int = 0) -> None:
        self.deaths += 1
        now = time.time()
        alive_seconds = max(0.0, now - self.episode_start_t)
        self.write_event(
            "death",
            reason=reason, killer=int(killer), area_lost=int(area_lost),
            alive_seconds=round(alive_seconds, 3),
        )

        trail_at_death = int(trail_len_at_death or 0)
        if trail_at_death > 0:
            target_area_estimate = (trail_at_death * trail_at_death) // 4
            self.write_event(
                "capture_fail",
                reason="died_before_return",
                trail_len_at_fail=trail_at_death,
                target_area_estimate=target_area_estimate,
                alive_seconds=round(alive_seconds, 3),
                killer=int(killer),
            )
            self.capture_fails += 1
            self.round_capture_fails += 1
            self.wasted_trail_total += trail_at_death
            self.round_wasted_trail_total += trail_at_death

        self.mark_milestone("death")

        avg_cap = (
            self.captured_area_total / self.captures_count
            if self.captures_count > 0 else 0.0
        )
        self.write_event(
            "episode_end",
            captured_area_total=self.captured_area_total,
            captured_length_total=self.captured_length_total,
            kills=self.kills,
            deaths=self.deaths,
            alive_seconds=round(alive_seconds, 3),
            survived=False,
            capture_fails=self.capture_fails,
            hunt_fails=0,
            explore_fails=0,
            wasted_trail_total=self.wasted_trail_total,
            final_area=int(area_lost),
            n_captures=int(self.captures_count),
            avg_capture_area=round(avg_cap, 3),
            avg_area_1m_at_end=round(float(getattr(self, "avg_area_1m_at_end", 0.0)), 3),
            end_kills=int(self.kills),
        )

    def log_kill(self, victim: int, victim_name: str, via: str) -> None:
        self.kills += 1
        self.write_event("kill", victim=int(victim), victim_name=victim_name, via=via)

    def log_respawn(self, x: int, y: int) -> None:
        self.episode_id += 1
        self.episode_start_t = time.time()
        self.captured_area_total = 0
        self.captured_length_total = 0
        self.capture_fails = 0
        self.wasted_trail_total = 0
        self.write_event("respawn", x=int(x), y=int(y))

    def close(self) -> None:
        now = time.time()
        alive_seconds = max(0.0, now - self.episode_start_t)
        avg = (
            self.captured_area_total / self.captures_count
            if self.captures_count > 0 else 0.0
        )
        try:
            if self.tick_buffer:
                self.flush_buffer(OUTCOME_NEUTRAL)
            self.write_event(
                "round_summary",
                rounds=1,
                total_captured_area=self.captured_area_total,
                total_captured_length=self.captured_length_total,
                kills=self.kills,
                deaths=self.deaths,
                avg_area_per_capture=round(avg, 3),
                max_area=self.max_area,
                capture_fails=self.round_capture_fails,
                hunt_fails=0,
                explore_fails=0,
                wasted_trail_total=self.round_wasted_trail_total,
            )
            self.write_event(
                "episode_end",
                captured_area_total=self.captured_area_total,
                captured_length_total=self.captured_length_total,
                kills=self.kills,
                deaths=self.deaths,
                alive_seconds=round(alive_seconds, 3),
                survived=True,
                capture_fails=self.capture_fails,
                hunt_fails=0,
                explore_fails=0,
                wasted_trail_total=self.wasted_trail_total,
            )
        except Exception as exc:
            logger.error(
                f"close failed: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
            )
        finally:
            if self.fp is not None:
                try:
                    self.fp.close()
                except Exception:
                    pass
            self.fp = None
            self.writer = None


def main():
    pass


if __name__ == "__main__":
    main()
