import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

from common.database import DATABASE
from common.inventory import default_loadout, merge_loadout
from config.settings import BASE_DIR, CLIENT_DIR


DATA_DIR = BASE_DIR / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SESSION_FILE = DATA_DIR / "current_session.json"
GAME_DOC_PATHS = [
    CLIENT_DIR / "Documents" / "user_info.txt",
    CLIENT_DIR / "ros" / "Documents" / "user_info.txt",
]

_migration_lock = threading.Lock()


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with SHA-256 and a per-account random 128-bit salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return digest, salt


def _legacy_game_info() -> dict:
    for path in GAME_DOC_PATHS:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as file:
                info = json.loads(file.read().strip())
            if isinstance(info, dict):
                return info
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _normalize_account(username: str, account: dict) -> dict:
    migrated = dict(account)
    migrated["username"] = username.strip().lower()
    if "password_hash" not in migrated and "password" in migrated:
        migrated["password_hash"], migrated["password_salt"] = hash_password(
            str(migrated.pop("password"))
        )
    migrated.setdefault("password_hash", "")
    migrated.setdefault("password_salt", "")
    migrated.setdefault("loadout", default_loadout())
    migrated["loadout"] = merge_loadout(migrated["loadout"])
    migrated.setdefault("role_id", 10001)
    migrated.setdefault("nickname", "")
    migrated.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    migrated.setdefault("last_login", "")
    migrated.setdefault("user_info", {})
    migrated.setdefault("created", bool(migrated.get("nickname")))
    return migrated


def initialize_storage():
    """Import existing accounts.json once, keeping the JSON file as a migration source."""
    if DATABASE.get_meta("legacy_accounts_imported") == "1":
        return

    with _migration_lock:
        if DATABASE.get_meta("legacy_accounts_imported") == "1":
            return

        ensure_data_dir()
        if ACCOUNTS_FILE.exists():
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as file:
                legacy_data = json.load(file)
            if not isinstance(legacy_data, dict) or not isinstance(legacy_data.get("accounts", {}), dict):
                raise ValueError(f"Invalid account data structure in {ACCOUNTS_FILE}")
            accounts = legacy_data.get("accounts", {})
            last_logged_in = str(legacy_data.get("last_logged_in", ""))
        else:
            info = _legacy_game_info()
            nickname = str(info.get("playerNickname", "")).strip()
            username = "embege" if nickname else "user1"
            password_hash, password_salt = hash_password("123")
            accounts = {
                username: {
                    "password_hash": password_hash,
                    "password_salt": password_salt,
                    "role_id": int(info.get("roleID", 10001)) if nickname else 10001,
                    "nickname": nickname,
                    "created": bool(nickname),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_login": "",
                    "user_info": info if nickname else {},
                }
            }
            last_logged_in = username

        normalized = [
            _normalize_account(username, account)
            for username, account in accounts.items()
            if isinstance(username, str) and isinstance(account, dict)
        ]
        with DATABASE.transaction() as connection:
            for account in normalized:
                DATABASE.upsert_account(account, connection)
            if last_logged_in:
                DATABASE.set_meta("last_logged_in", last_logged_in.strip().lower(), connection)
            DATABASE.set_meta("legacy_accounts_imported", "1", connection)


def load_accounts_data():
    initialize_storage()
    return {
        "accounts": DATABASE.list_accounts(),
        "last_logged_in": DATABASE.get_meta("last_logged_in") or "",
    }


def save_accounts_data(data):
    initialize_storage()
    accounts = data.get("accounts", {})
    if not isinstance(accounts, dict):
        raise ValueError("accounts must be a mapping")
    with DATABASE.transaction() as connection:
        for username, account in accounts.items():
            if not isinstance(account, dict):
                raise ValueError(f"Account record for {username!r} must be a mapping")
            normalized = _normalize_account(username, account)
            DATABASE.upsert_account(normalized, connection)
        last_logged_in = str(data.get("last_logged_in", "")).strip().lower()
        if last_logged_in:
            DATABASE.set_meta("last_logged_in", last_logged_in, connection)


def get_account(username):
    initialize_storage()
    return DATABASE.get_account(username)


def verify_credentials(username: str, password: str):
    """Return the account record for valid credentials, otherwise None."""
    initialize_storage()
    account = DATABASE.get_account(username)
    if account is None:
        return None

    stored_hash = account.get("password_hash")
    salt = account.get("password_salt")
    if not stored_hash or not salt:
        return None
    candidate_hash, _ = hash_password(password, salt)
    if not hmac.compare_digest(candidate_hash, stored_hash):
        return None

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    DATABASE.update_login_time(account["username"], timestamp)
    account["last_login"] = timestamp
    return account


def get_loadout(username):
    account = get_account(username)
    if account is None:
        return default_loadout()
    return merge_loadout(account.get("loadout"))


def update_loadout(username, updates):
    """Persist player appearance choices while keeping premium state disabled."""
    account = get_account(username)
    if account is None:
        return None

    loadout = merge_loadout(account.get("loadout"))
    allowed = (
        "costume_item_id",
        "weapon_skin_item_id",
        "parachute_item_id",
        "vehicle_skin_item_id",
        "profile_frame_item_id",
    )
    for field in allowed:
        value = updates.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            loadout[field] = value
    loadout["vip_level"] = 0
    loadout["premium"] = False
    if not DATABASE.update_loadout(username, loadout):
        return None
    return loadout


def authenticate(username, password):
    username = username.strip().lower()
    if get_account(username) is None:
        return None, "Account not found!"
    account = verify_credentials(username, password)
    if account is None:
        return None, "Incorrect password!"
    return account, "OK"


def register(username, password, nickname=""):
    username = username.strip().lower()
    if not username or len(username) < 3:
        return None, "Username must be at least 3 characters!"
    if not password or len(password) < 3:
        return None, "Password must be at least 3 characters!"
    initialize_storage()

    clean_nickname = nickname.strip()
    created = bool(clean_nickname)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    password_hash, password_salt = hash_password(password)
    with DATABASE.transaction() as connection:
        row = connection.execute("SELECT 1 FROM accounts WHERE username = ?", (username,)).fetchone()
        if row:
            return None, f"Username '{username}' is already registered!"
        role_id = connection.execute(
            "SELECT COALESCE(MAX(role_id), 10000) + 1 FROM accounts"
        ).fetchone()[0]
        user_info = {
            "playerAccount": username,
            "roleID": role_id,
            "playerNickname": clean_nickname,
            "defaultServerName": "local",
            "defaultZoneName": "local",
            "defaultGroupId": "10001",
            "isLogin": True,
            "announcement": "d41d8cd98f00b204e9800998ecf8427e",
            "showNumOfA": 2,
            "playerUID": None,
            "remindGuestBindTimestamp": 0,
            "serverRoleInfo": {
                "10001": {"groupId": "10001", "roleID": role_id, "playerUID": None}
            },
        }
        account = {
            "username": username,
            "password_hash": password_hash,
            "password_salt": password_salt,
            "loadout": default_loadout(),
            "role_id": role_id,
            "nickname": clean_nickname,
            "created": created,
            "created_at": timestamp,
            "last_login": timestamp,
            "user_info": user_info,
        }
        DATABASE.upsert_account(account, connection)
        DATABASE.set_meta("last_logged_in", username, connection)
        return account, "OK"


def delete_account(username):
    initialize_storage()
    key = username.strip().lower()
    deleted = DATABASE.delete_account(key)
    if deleted and DATABASE.get_meta("last_logged_in") == key:
        remaining = DATABASE.list_accounts()
        DATABASE.set_meta("last_logged_in", next(iter(remaining), ""))
    return deleted


def get_last_account():
    data = load_accounts_data()
    last = data["last_logged_in"]
    if last and last in data["accounts"]:
        return data["accounts"][last]
    return next(iter(data["accounts"].values()), None)


def sync_to_game(account):
    """Write account information into game's user_info.txt files."""
    user_info = account.get("user_info", {})
    if not user_info:
        user_info = {
            "playerAccount": account["username"],
            "roleID": account["role_id"],
            "playerNickname": account.get("nickname", ""),
            "defaultServerName": "local",
            "defaultZoneName": "local",
            "defaultGroupId": "10001",
            "isLogin": True,
            "announcement": "d41d8cd98f00b204e9800998ecf8427e",
            "showNumOfA": 2,
            "playerUID": None,
            "remindGuestBindTimestamp": 0,
            "serverRoleInfo": {
                "10001": {
                    "groupId": "10001",
                    "roleID": account["role_id"],
                    "playerUID": None,
                }
            },
        }
    else:
        user_info["playerAccount"] = account["username"]
        user_info["roleID"] = account["role_id"]
        user_info["defaultServerName"] = "local"
        user_info["defaultZoneName"] = "local"
        user_info["defaultGroupId"] = "10001"
        user_info["playerNickname"] = account.get("nickname", "")
        user_info["isLogin"] = True

    text = json.dumps(user_info, ensure_ascii=False)
    for path in GAME_DOC_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                file.write(text)
        except OSError as error:
            print(f"[!] Warning writing {path}: {error}")

    ensure_data_dir()
    session_info = {
        "username": account["username"],
        "role_id": account["role_id"],
        "nickname": account.get("nickname", ""),
        "created": account.get("created", False),
        "fallback_mode": "uimain" if account.get("created") and account.get("nickname") else "select",
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as file:
        json.dump(session_info, file, indent=2)


def sync_from_game(username):
    """Read game's user_info.txt and update the SQLite account record."""
    key = username.strip().lower()
    data = load_accounts_data()
    account = data["accounts"].get(key)
    if not account:
        return

    game_info = _legacy_game_info()
    if not game_info:
        return
    nickname = str(game_info.get("playerNickname", "")).strip()
    role_id = game_info.get("roleID", account.get("role_id", 10001))
    if nickname:
        account["nickname"] = nickname
        account["created"] = True
    if role_id:
        account["role_id"] = int(role_id)
    account["user_info"] = game_info
    save_accounts_data(data)

    ensure_data_dir()
    session_info = {
        "username": account["username"],
        "role_id": account["role_id"],
        "nickname": account.get("nickname", ""),
        "created": account.get("created", False),
        "fallback_mode": "uimain" if account.get("created") and account.get("nickname") else "select",
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as file:
        json.dump(session_info, file, indent=2)


initialize_storage()
