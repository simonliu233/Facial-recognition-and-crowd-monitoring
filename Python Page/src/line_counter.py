"""Deterministic, detector-independent bidirectional crossing state machine."""
from dataclasses import dataclass
import math
import time
import uuid

@dataclass
class TrackState:
    last_seen: float
    hits: int = 0
    stable_side: int = 0
    candidate_side: int = 0
    candidate_hits: int = 0

class LineCrossingCounter:
    """Confirm both sides of a dead band using observed bottom-centre points.

    There is no global cooldown, no area-population estimate and no extrapolated
    crossing. One person can return across the line after confirming the far side.
    Coordinates are normalized to the image, so resolution changes are harmless.
    """
    def __init__(self, axis="x", position=0.5, band=0.04, roi=(0.0, 1.0),
                 confirm_frames=2, min_hits=3, max_idle=4.0):
        self.configure(axis, position, band, roi)
        self.confirm_frames = int(confirm_frames)
        self.min_hits = int(min_hits)
        self.max_idle = float(max_idle)
        self.tracks = {}
        self.sequence = 0
        self.session = uuid.uuid4().hex

    def configure(self, axis, position, band, roi):
        position, band = float(position), float(band)
        lo, hi = map(float, roi)
        if axis not in ("x", "y"):
            raise ValueError("axis must be x or y")
        if not all(math.isfinite(v) for v in (position, band, lo, hi)):
            raise ValueError("Configuration must contain finite numbers")
        if not 0.1 <= position <= 0.9 or not 0.01 <= band <= 0.15:
            raise ValueError("Line position must be 0.1–0.9; dead band must be 0.01–0.15")
        if position - band <= 0 or position + band >= 1:
            raise ValueError("Dead band must fit inside the frame")
        if not 0 <= lo < hi <= 1:
            raise ValueError("ROI limits must satisfy 0 <= start < end <= 1")
        self.axis, self.position, self.band, self.roi = axis, position, band, (lo, hi)
        if hasattr(self, "tracks"):
            self.clear()

    def clear(self):
        self.tracks.clear()
        self.session = uuid.uuid4().hex
        self.sequence = 0

    def update(self, observations, now=None):
        now = time.monotonic() if now is None else float(now)
        self.tracks = {key: state for key, state in self.tracks.items()
                       if now - state.last_seen <= self.max_idle}
        events = []
        for track_id, x, y in observations:
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
                continue
            value, transverse = (x, y) if self.axis == "x" else (y, x)
            if not self.roi[0] <= transverse <= self.roi[1]:
                self.tracks.pop(track_id, None)
                continue
            state = self.tracks.setdefault(track_id, TrackState(now))
            state.last_seen = now
            state.hits += 1
            side = -1 if value < self.position - self.band else 1 if value > self.position + self.band else 0
            if side == 0:
                state.candidate_side = state.candidate_hits = 0
                continue
            if side == state.stable_side:
                state.candidate_side = state.candidate_hits = 0
                continue
            if state.candidate_side != side:
                state.candidate_side, state.candidate_hits = side, 1
            else:
                state.candidate_hits += 1
            if state.candidate_hits < self.confirm_frames:
                continue
            previous = state.stable_side
            if previous and state.hits < self.min_hits:
                continue
            state.stable_side = side
            state.candidate_side = state.candidate_hits = 0
            if previous:
                self.sequence += 1
                events.append({
                    "event_id": f"{self.session}:{self.sequence}",
                    "track_id": int(track_id),
                    "direction": "left_to_right" if side > previous else "right_to_left",
                })
        return events

    def settings(self):
        return {"axis": self.axis, "line_position": self.position,
                "dead_band": self.band, "roi_start": self.roi[0], "roi_end": self.roi[1]}
