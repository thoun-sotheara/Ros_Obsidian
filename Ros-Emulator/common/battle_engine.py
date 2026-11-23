from dataclasses import dataclass, field
import math
import threading
import time
import uuid

from common.database import DATABASE
from common.room_manager import FINISHED, IN_PROGRESS, ROOM_MANAGER


@dataclass
class CombatPlayer:
    player_id: str
    hp: int = 100
    armor: int = 0
    alive: bool = True
    kills: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    weapon: str | None = None
    ammo: int = 0
    medkits: int = 0


@dataclass
class LootItem:
    loot_id: str
    item_type: str
    x: float
    y: float
    z: float
    weapon: str | None = None
    damage: int = 0
    ammo: int = 0
    armor: int = 0


@dataclass
class BattleRoom:
    room_id: str
    map_name: str
    state: str
    match_id: str
    started_at: float
    players: dict[str, CombatPlayer]
    loot: dict[str, LootItem]
    center_x: float = 0.0
    center_y: float = 0.0
    radius: float = 500.0
    zone_phase: int = 0
    last_zone_shrink: float = field(default_factory=time.monotonic)
    winner: str | None = None
    result_recorded: bool = False


class BattleEngine:
    """Thread-safe server-authoritative combat and safe-zone simulation."""

    ZONE_INTERVAL_SECONDS = 10.0
    ZONE_SHRINK_PER_PHASE = 50.0
    ZONE_DAMAGE_PER_TICK = 5
    LOOT_PICKUP_DISTANCE = 8.0
    WEAPONS = {
        "M4A1": {"damage": 34, "ammo": 30, "range": 500.0},
        "AKM": {"damage": 40, "ammo": 30, "range": 400.0},
        "AWM": {"damage": 100, "ammo": 5, "range": 1000.0},
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rooms: dict[str, BattleRoom] = {}

    def start_room(self, room_snapshot: dict) -> dict:
        room_id = room_snapshot["room_id"]
        spawns = room_snapshot.get("spawn_points", {})
        players = {
            username: CombatPlayer(
                player_id=username,
                x=float(spawn.get("x", 0.0)),
                y=float(spawn.get("y", 0.0)),
                z=float(spawn.get("z", 0.0)),
            )
            for username, spawn in spawns.items()
        }
        loot: dict[str, LootItem] = {}
        for player in players.values():
            prefix = player.player_id.replace(" ", "_")
            loot[f"loot-weapon-m4-{prefix}"] = LootItem(
                f"loot-weapon-m4-{prefix}", "weapon", player.x + 3.0, player.y, player.z,
                weapon="M4A1", damage=34, ammo=30,
            )
            loot[f"loot-weapon-akm-{prefix}"] = LootItem(
                f"loot-weapon-akm-{prefix}", "weapon", player.x + 6.0, player.y, player.z,
                weapon="AKM", damage=40, ammo=30,
            )
            loot[f"loot-weapon-awm-{prefix}"] = LootItem(
                f"loot-weapon-awm-{prefix}", "weapon", player.x + 9.0, player.y, player.z,
                weapon="AWM", damage=100, ammo=5,
            )
            loot[f"loot-armor-2-{prefix}"] = LootItem(
                f"loot-armor-2-{prefix}", "armor", player.x + 4.0, player.y, player.z,
                armor=50,
            )
            loot[f"loot-medkit-{prefix}"] = LootItem(
                f"loot-medkit-{prefix}", "medkit", player.x + 5.0, player.y, player.z,
            )

        with self._lock:
            if room_id in self._rooms:
                return self._snapshot(self._rooms[room_id])
            self._rooms[room_id] = BattleRoom(
                room_id=room_id,
                map_name=room_snapshot.get("map", "Ghillie Island"),
                state=IN_PROGRESS,
                match_id=uuid.uuid4().hex,
                started_at=time.monotonic(),
                players=players,
                loot=loot,
            )
            return self._snapshot(self._rooms[room_id])

    def update_position(
        self, room_id: str, player_id: str, x: float, y: float, z: float, yaw: float
    ) -> dict:
        values = (x, y, z, yaw)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("position and yaw values must be finite")
        if any(abs(float(value)) > 10000 for value in values[:3]):
            raise ValueError("position is outside the supported map bounds")
        with self._lock:
            room = self._active_room(room_id)
            player = self._alive_player(room, player_id)
            player.x, player.y, player.z, player.yaw = map(float, values)
            return {"type": "movement", "room_id": room_id, "player": self._player_snapshot(player)}

    def pickup_loot(self, room_id: str, player_id: str, loot_id: str) -> dict:
        with self._lock:
            room = self._active_room(room_id)
            player = self._alive_player(room, player_id)
            loot = room.loot.get(loot_id)
            if loot is None:
                raise ValueError("loot item is not available")
            if self._distance(player.x, player.y, player.z, loot.x, loot.y, loot.z) > self.LOOT_PICKUP_DISTANCE:
                raise ValueError("loot item is too far away")
            if loot.item_type == "weapon":
                player.weapon = loot.weapon
                player.ammo += loot.ammo
            elif loot.item_type == "armor":
                player.armor = max(player.armor, loot.armor)
            elif loot.item_type == "medkit":
                player.medkits += 1
            del room.loot[loot_id]
            return {
                "type": "loot_picked",
                "room_id": room_id,
                "player_id": player_id,
                "item": self._loot_snapshot(loot),
                "player": self._player_snapshot(player),
            }

    def process_fire(
        self,
        room_id: str,
        shooter_id: str,
        target_id: str,
        hit_distance: float | None = None,
    ) -> dict:
        del hit_distance  # Never trust a client-supplied distance; derive it from server positions.
        with self._lock:
            room = self._active_room(room_id)
            shooter = self._alive_player(room, shooter_id)
            target = self._alive_player(room, target_id)
            if shooter_id == target_id:
                raise ValueError("cannot target yourself")
            if not shooter.weapon:
                raise ValueError("no equipped weapon")
            if shooter.ammo <= 0:
                raise ValueError("no ammunition")
            weapon = self.WEAPONS.get(shooter.weapon)
            if weapon is None:
                raise ValueError("equipped weapon is not supported")
            distance = self._distance(shooter.x, shooter.y, shooter.z, target.x, target.y, target.z)
            if distance > weapon["range"]:
                raise ValueError("target is outside weapon range")

            shooter.ammo -= 1
            raw_damage = weapon["damage"]
            absorbed = min(target.armor, raw_damage // 2)
            target.armor -= absorbed
            damage = raw_damage - absorbed
            target.hp = max(0, target.hp - damage)
            eliminated = target.hp == 0
            if eliminated:
                target.alive = False
                shooter.kills += 1

            alive_players = [player for player in room.players.values() if player.alive]
            winner = None
            if eliminated and len(alive_players) == 1:
                winner = alive_players[0].player_id
                room.state = FINISHED
                room.winner = winner
                ROOM_MANAGER.finish(room_id)
                self._record_result(room)

            return {
                "type": "elimination" if eliminated else "damage",
                "room_id": room_id,
                "shooter_id": shooter_id,
                "target": target_id,
                "distance": round(distance, 2),
                "damage": damage,
                "target_hp": target.hp,
                "target_armor": target.armor,
                "eliminated": eliminated,
                "shooter": self._player_snapshot(shooter),
                "target_player": self._player_snapshot(target),
                "alive_count": len(alive_players),
                "winner": winner,
                "state": room.state,
            }

    def state(self, room_id: str) -> dict:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                raise ValueError("battle room is not initialized")
            return self._snapshot(room)

    def tick(self, now: float | None = None) -> list[dict]:
        tick_time = time.monotonic() if now is None else now
        events = []
        with self._lock:
            for room in self._rooms.values():
                if room.state != IN_PROGRESS or tick_time - room.last_zone_shrink < self.ZONE_INTERVAL_SECONDS:
                    continue
                room.last_zone_shrink = tick_time
                room.zone_phase += 1
                room.radius = max(0.0, room.radius - self.ZONE_SHRINK_PER_PHASE)
                zone_event = {
                    "type": "zone_update",
                    "room_id": room.room_id,
                    "center_x": room.center_x,
                    "center_y": room.center_y,
                    "radius": room.radius,
                    "phase": room.zone_phase,
                }
                for player in room.players.values():
                    if player.alive and self._distance(player.x, 0.0, player.z, room.center_x, 0.0, room.center_y) > room.radius:
                        player.hp = max(0, player.hp - self.ZONE_DAMAGE_PER_TICK)
                        if player.hp == 0:
                            player.alive = False
                            zone_event.setdefault("eliminated", []).append(player.player_id)
                alive_players = [player for player in room.players.values() if player.alive]
                if len(alive_players) <= 1:
                    room.state = FINISHED
                    room.winner = alive_players[0].player_id if alive_players else None
                    zone_event["winner"] = room.winner
                    zone_event["state"] = FINISHED
                    ROOM_MANAGER.finish(room.room_id)
                    self._record_result(room)
                zone_event["alive_count"] = len(alive_players)
                events.append(zone_event)
        return events

    def _active_room(self, room_id: str) -> BattleRoom:
        room = self._rooms.get(room_id)
        if room is None or room.state != IN_PROGRESS:
            raise ValueError("battle room is not in progress")
        return room

    @staticmethod
    def _alive_player(room: BattleRoom, player_id: str) -> CombatPlayer:
        player = room.players.get(player_id)
        if player is None or not player.alive:
            raise ValueError("player is not alive in this room")
        return player

    @staticmethod
    def _distance(x1: float, y1: float, z1: float, x2: float, y2: float, z2: float) -> float:
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)

    @staticmethod
    def _player_snapshot(player: CombatPlayer) -> dict:
        return {
            "player_id": player.player_id,
            "hp": player.hp,
            "armor": player.armor,
            "alive": player.alive,
            "kills": player.kills,
            "position": {"x": player.x, "y": player.y, "z": player.z},
            "yaw": player.yaw,
            "weapon": player.weapon,
            "ammo": player.ammo,
            "medkits": player.medkits,
        }

    @staticmethod
    def _loot_snapshot(loot: LootItem) -> dict:
        return {
            "loot_id": loot.loot_id,
            "item_type": loot.item_type,
            "item": loot.weapon if loot.weapon else loot.item_type,
            "position": {"x": loot.x, "y": loot.y, "z": loot.z},
        }

    def _snapshot(self, room: BattleRoom) -> dict:
        return {
            "type": "battle_state",
            "room_id": room.room_id,
            "map": room.map_name,
            "state": room.state,
            "players": {player_id: self._player_snapshot(player) for player_id, player in room.players.items()},
            "alive_count": sum(player.alive for player in room.players.values()),
            "loot": [self._loot_snapshot(item) for item in room.loot.values()],
            "safe_zone": {
                "center_x": room.center_x,
                "center_y": room.center_y,
                "radius": room.radius,
                "phase": room.zone_phase,
            },
            "winner": room.winner,
        }

    @staticmethod
    def _record_result(room: BattleRoom) -> None:
        if room.result_recorded:
            return
        DATABASE.record_match(
            match_id=room.match_id,
            room_id=room.room_id,
            map_name=room.map_name,
            winner_username=room.winner,
            duration_sec=time.monotonic() - room.started_at,
            participants=[
                {"username": player.player_id, "kills": player.kills}
                for player in room.players.values()
            ],
        )
        room.result_recorded = True


BATTLE_ENGINE = BattleEngine()
