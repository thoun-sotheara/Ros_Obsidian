from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

from config.settings import BASE_DIR


DATABASE_PATH = BASE_DIR / "data" / "ros_server.db"


class Database:
    """Serialized SQLite access using a fresh WAL-enabled connection per operation."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            connection = sqlite3.connect(self.path, timeout=30)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA foreign_keys = ON")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS accounts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        password_hash TEXT NOT NULL,
                        password_salt TEXT NOT NULL,
                        role_id INTEGER NOT NULL,
                        nickname TEXT NOT NULL DEFAULT '',
                        loadout_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        last_login TEXT NOT NULL DEFAULT '',
                        user_info_json TEXT NOT NULL DEFAULT '{}',
                        created INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS match_history (
                        match_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        map_name TEXT NOT NULL,
                        winner_username TEXT,
                        total_players INTEGER NOT NULL,
                        duration_sec REAL NOT NULL,
                        finished_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS player_stats (
                        username TEXT PRIMARY KEY COLLATE NOCASE,
                        matches_played INTEGER NOT NULL DEFAULT 0,
                        wins INTEGER NOT NULL DEFAULT 0,
                        kills INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS app_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_leaderboard
                        ON player_stats(wins DESC, kills DESC);
                    """
                )
                connection.commit()
            finally:
                connection.close()

    @staticmethod
    def _account_values(account: dict) -> tuple:
        return (
            account["username"].strip().lower(),
            account.get("password_hash", ""),
            account.get("password_salt", ""),
            int(account.get("role_id", 0)),
            account.get("nickname", ""),
            json.dumps(account.get("loadout", {}), separators=(",", ":"), ensure_ascii=False),
            account.get("created_at", ""),
            account.get("last_login", ""),
            json.dumps(account.get("user_info", {}), separators=(",", ":"), ensure_ascii=False),
            int(bool(account.get("created", False))),
        )

    @staticmethod
    def account_dict(row: sqlite3.Row) -> dict:
        return {
            "username": row["username"],
            "password_hash": row["password_hash"],
            "password_salt": row["password_salt"],
            "role_id": row["role_id"],
            "nickname": row["nickname"],
            "loadout": json.loads(row["loadout_json"]),
            "created_at": row["created_at"],
            "last_login": row["last_login"],
            "user_info": json.loads(row["user_info_json"]),
            "created": bool(row["created"]),
        }

    def upsert_account(self, account: dict, connection: sqlite3.Connection | None = None) -> None:
        values = self._account_values(account)
        statement = """
            INSERT INTO accounts (
                username, password_hash, password_salt, role_id, nickname,
                loadout_json, created_at, last_login, user_info_json, created
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                password_salt=excluded.password_salt,
                role_id=excluded.role_id,
                nickname=excluded.nickname,
                loadout_json=excluded.loadout_json,
                created_at=excluded.created_at,
                last_login=excluded.last_login,
                user_info_json=excluded.user_info_json,
                created=excluded.created
        """
        if connection is not None:
            connection.execute(statement, values)
            return
        with self.transaction() as conn:
            conn.execute(statement, values)

    def get_account(self, username: str) -> dict | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE username = ? COLLATE NOCASE",
                (username.strip().lower(),),
            ).fetchone()
            return self.account_dict(row) if row else None

    def list_accounts(self) -> dict[str, dict]:
        with self.transaction() as connection:
            rows = connection.execute("SELECT * FROM accounts ORDER BY id").fetchall()
            return {row["username"]: self.account_dict(row) for row in rows}

    def get_meta(self, key: str) -> str | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str, connection: sqlite3.Connection | None = None) -> None:
        statement = """
            INSERT INTO app_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
        if connection is not None:
            connection.execute(statement, (key, value))
            return
        with self.transaction() as conn:
            conn.execute(statement, (key, value))

    def update_login_time(self, username: str, timestamp: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE accounts SET last_login = ? WHERE username = ? COLLATE NOCASE",
                (timestamp, username.strip().lower()),
            )
            self.set_meta("last_logged_in", username.strip().lower(), connection)

    def delete_account(self, username: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM accounts WHERE username = ? COLLATE NOCASE",
                (username.strip().lower(),),
            )
            return cursor.rowcount > 0

    def update_loadout(self, username: str, loadout: dict) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE accounts SET loadout_json = ? WHERE username = ? COLLATE NOCASE",
                (json.dumps(loadout, separators=(",", ":"), ensure_ascii=False), username.strip().lower()),
            )
            return cursor.rowcount > 0

    def record_match(
        self,
        match_id: str,
        room_id: str,
        map_name: str,
        winner_username: str | None,
        duration_sec: float,
        participants: list[dict],
    ) -> bool:
        """Insert a match and update all participant aggregates exactly once."""
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO match_history (
                    match_id, room_id, map_name, winner_username,
                    total_players, duration_sec, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    match_id,
                    room_id,
                    map_name,
                    winner_username,
                    len(participants),
                    max(0.0, float(duration_sec)),
                ),
            )
            if cursor.rowcount == 0:
                return False

            for player in participants:
                username = player["username"].strip().lower()
                wins = int(username == (winner_username or "").strip().lower())
                kills = max(0, int(player.get("kills", 0)))
                connection.execute(
                    """
                    INSERT INTO player_stats(username, matches_played, wins, kills)
                    VALUES (?, 1, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        matches_played = player_stats.matches_played + 1,
                        wins = player_stats.wins + excluded.wins,
                        kills = player_stats.kills + excluded.kills
                    """,
                    (username, wins, kills),
                )
            return True

    def get_leaderboard(self, limit: int = 20) -> list[dict]:
        bounded_limit = max(1, min(int(limit), 100))
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT s.username, COALESCE(a.nickname, '') AS nickname,
                       s.matches_played, s.wins, s.kills
                FROM player_stats AS s
                LEFT JOIN accounts AS a ON a.username = s.username COLLATE NOCASE
                ORDER BY s.wins DESC, s.kills DESC, s.username COLLATE NOCASE ASC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
            return [dict(row) for row in rows]


DATABASE = Database()
