import json
import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
CERTS_DIR = BASE_DIR / "certs"
CRYPTO_DIR = BASE_DIR / "crypto"
SCHEMAS_DIR = BASE_DIR / "schemas"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_JSON_PATH = BASE_DIR / "config.json"

# Ensure logs directory exists
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Default Configuration
DEFAULT_CONFIG = {
    "_comment": "Rules of Survival (RoS) Server & Client Central Configuration",
    "game_directory": str(Path(r"D:\Game\RosOfflineReborn")),
    "server_host": "127.0.0.1",
    "bind_host": "0.0.0.0",
    "http_port": 80,
    "https_port": 443,
    "loginapp_port": 20013,
    "baseapp_port": 20015,
    "server_name": "local",
    "room_map_name": "Ghillie Island",
    "room_max_players": 100,
    "room_min_players": 2,
    "room_countdown_seconds": 0.5
}

# Load config.json if present, or create with defaults
cfg = {}
if CONFIG_JSON_PATH.exists():
    try:
        with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[!] Warning: Failed to parse {CONFIG_JSON_PATH}: {e}")
        cfg = {}
else:
    try:
        with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        cfg = DEFAULT_CONFIG.copy()
    except Exception:
        cfg = {}

# Client Directory (Config JSON > Env Var > Default)
client_path_str = os.environ.get("ROS_CLIENT_DIR") or cfg.get("game_directory") or DEFAULT_CONFIG["game_directory"]
CLIENT_DIR = Path(client_path_str)

# Network Settings
BIND_HOST = os.environ.get("ROS_BIND_HOST") or cfg.get("bind_host") or DEFAULT_CONFIG["bind_host"]
PUBLIC_HOST = (
    os.environ.get("ROS_PUBLIC_HOST")
    or cfg.get("public_host")
    or cfg.get("server_host")
    or DEFAULT_CONFIG["server_host"]
)

# Ports
HTTP_PORT = int(os.environ.get("ROS_HTTP_PORT") or cfg.get("http_port") or DEFAULT_CONFIG["http_port"])
HTTPS_PORT = int(os.environ.get("ROS_HTTPS_PORT") or cfg.get("https_port") or DEFAULT_CONFIG["https_port"])
LOGINAPP_PORT = int(os.environ.get("ROS_LOGINAPP_PORT") or cfg.get("loginapp_port") or DEFAULT_CONFIG["loginapp_port"])
BASEAPP_PORT = int(os.environ.get("ROS_BASEAPP_PORT") or cfg.get("baseapp_port") or DEFAULT_CONFIG["baseapp_port"])

# Server Name
SERVER_NAME = os.environ.get("ROS_SERVER_NAME") or cfg.get("server_name") or DEFAULT_CONFIG["server_name"]

# Cryptography Files
CA_CRT_PATH = CERTS_DIR / "ca.crt"
SERVER_CRT_PATH = CERTS_DIR / "server.crt"
SERVER_KEY_PATH = CERTS_DIR / "server.key"

LOGINAPP_PRIV_KEY = CRYPTO_DIR / "our_loginapp.priv.pem"
LOGINAPP_PUB_KEY = CRYPTO_DIR / "our_loginapp.pub.pem"
BFCTX_PATH = CRYPTO_DIR / "bfctx.bin"
ROOM_MAP_NAME = os.environ.get("ROS_ROOM_MAP", cfg.get("room_map_name", DEFAULT_CONFIG["room_map_name"]))
ROOM_MAX_PLAYERS = int(os.environ.get("ROS_ROOM_MAX_PLAYERS", cfg.get("room_max_players", DEFAULT_CONFIG["room_max_players"])))
ROOM_MIN_PLAYERS = int(os.environ.get("ROS_ROOM_MIN_PLAYERS", cfg.get("room_min_players", DEFAULT_CONFIG["room_min_players"])))
ROOM_COUNTDOWN_SECONDS = float(os.environ.get("ROS_ROOM_COUNTDOWN_SECONDS", cfg.get("room_countdown_seconds", DEFAULT_CONFIG["room_countdown_seconds"])))

# Schema
AVATAR_SCHEMA_PATH = SCHEMAS_DIR / "old_avatar_base_schema.json"

# DNS & Gate Configuration
DNS_RESPONSE_KEY = b"H%t).Dn@"
SERVER_LINE = f"{SERVER_NAME} 2 1 2 0 {SERVER_NAME} {PUBLIC_HOST}:{LOGINAPP_PORT} {PUBLIC_HOST}:{LOGINAPP_PORT} {PUBLIC_HOST}:{LOGINAPP_PORT} 10001 {PUBLIC_HOST}:{LOGINAPP_PORT}"
