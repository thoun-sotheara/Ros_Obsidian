from dataclasses import dataclass, field
import threading
import time

from config.settings import (
    ROOM_COUNTDOWN_SECONDS,
    ROOM_MAP_NAME,
    ROOM_MAX_PLAYERS,
    ROOM_MIN_PLAYERS,
)


WAITING = "WAITING"
COUNTDOWN = "COUNTDOWN"
IN_PROGRESS = "IN_PROGRESS"
FINISHED = "FINISHED"


@dataclass
class MatchRoom:
    room_id: str
    map_name: str
    max_players: int
    min_players: int
    countdown_seconds: float
    state: str = WAITING
    players: list[str] = field(default_factory=list)
    countdown_end: float | None = None
    spawn_points: dict[str, dict[str, float]] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)


class RoomManager:
    """Minimal thread-safe Battle Royale queue and room lifecycle manager."""

    def __init__(
        self,
        map_name: str = ROOM_MAP_NAME,
        max_players: int = ROOM_MAX_PLAYERS,
        min_players: int = ROOM_MIN_PLAYERS,
        countdown_seconds: float = ROOM_COUNTDOWN_SECONDS,
    ) -> None:
        if max_players < 1:
            raise ValueError("room max_players must be positive")
        if min_players < 1 or min_players > max_players:
            raise ValueError("room min_players must be between 1 and max_players")
        if countdown_seconds < 0:
            raise ValueError("room countdown_seconds cannot be negative")
        self.map_name = map_name
        self.max_players = max_players
        self.min_players = min_players
        self.countdown_seconds = countdown_seconds
        self._lock = threading.RLock()
        self._rooms: dict[str, MatchRoom] = {}
        self._player_rooms: dict[str, str] = {}
        self._next_room_id = 1
        self._transition_callback = None

    def set_transition_callback(self, callback) -> None:
        self._transition_callback = callback

    def join(self, username: str) -> dict:
        user = username.strip().lower()
        if not user:
            raise ValueError("username is required to join matchmaking")
        with self._lock:
            existing_room_id = self._player_rooms.get(user)
            if existing_room_id:
                room = self._rooms[existing_room_id]
                if room.state != FINISHED:
                    return self._snapshot(room)
                self._player_rooms.pop(user, None)

            room = next(
                (
                    candidate for candidate in self._rooms.values()
                    if candidate.state in (WAITING, COUNTDOWN)
                    and len(candidate.players) < candidate.max_players
                ),
                None,
            )
            if room is None:
                room_id = f"room-{self._next_room_id:04d}"
                self._next_room_id += 1
                room = MatchRoom(
                    room_id=room_id,
                    map_name=self.map_name,
                    max_players=self.max_players,
                    min_players=self.min_players,
                    countdown_seconds=self.countdown_seconds,
                )
                self._rooms[room_id] = room

            room.players.append(user)
            self._player_rooms[user] = room.room_id
            if len(room.players) >= room.min_players and room.state == WAITING:
                room.state = COUNTDOWN
                room.countdown_end = time.monotonic() + room.countdown_seconds
                self._schedule_countdown(room)
            return self._snapshot(room)

    def leave(self, username: str) -> dict:
        user = username.strip().lower()
        with self._lock:
            room_id = self._player_rooms.get(user)
            if room_id is None:
                return {"room_id": None, "state": WAITING, "players": []}
            room = self._rooms[room_id]
            if room.state in (WAITING, COUNTDOWN):
                self._player_rooms.pop(user, None)
                room.players.remove(user)
                if room.state == COUNTDOWN and len(room.players) < room.min_players:
                    room.state = WAITING
                    room.countdown_end = None
                self._refresh_room(room)
            return self._snapshot(room)

    def status(self, username: str) -> dict:
        user = username.strip().lower()
        callback = None
        with self._lock:
            room_id = self._player_rooms.get(user)
            if room_id is None:
                return {"room_id": None, "state": WAITING, "players": []}
            room = self._rooms[room_id]
            transitioned = self._refresh_room(room)
            snapshot = self._snapshot(room)
            if transitioned:
                callback = self._transition_callback
        if callback is not None:
            callback(snapshot)
        return snapshot

    def finish(self, room_id: str) -> dict:
        with self._lock:
            room = self._rooms[room_id]
            room.state = FINISHED
            room.countdown_end = None
            return self._snapshot(room)

    def _schedule_countdown(self, room: MatchRoom) -> None:
        timer = threading.Timer(room.countdown_seconds, self._countdown_complete, args=(room.room_id,))
        timer.daemon = True
        timer.start()

    def _countdown_complete(self, room_id: str) -> None:
        callback = None
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None or room.state != COUNTDOWN:
                return
            remaining = (room.countdown_end or 0) - time.monotonic()
            if remaining > 0:
                timer = threading.Timer(remaining, self._countdown_complete, args=(room_id,))
                timer.daemon = True
                timer.start()
                return
            self._refresh_room(room)
            snapshot = self._snapshot(room)
            callback = self._transition_callback
        if callback is not None:
            callback(snapshot)

    def _refresh_room(self, room: MatchRoom) -> bool:
        if room.state == COUNTDOWN and room.countdown_end is not None:
            if time.monotonic() >= room.countdown_end:
                room.state = IN_PROGRESS
                room.countdown_end = None
                room.spawn_points = {
                    username: {
                        "x": float((index % 10) * 100),
                        "y": 0.0,
                        "z": float((index // 10) * 100),
                    }
                    for index, username in enumerate(room.players)
                }
                return True
        return False

    @staticmethod
    def _snapshot(room: MatchRoom) -> dict:
        return {
            "room_id": room.room_id,
            "state": room.state,
            "map": room.map_name,
            "players": list(room.players),
            "player_count": len(room.players),
            "max_players": room.max_players,
            "spawn_points": dict(room.spawn_points),
        }


ROOM_MANAGER = RoomManager()
