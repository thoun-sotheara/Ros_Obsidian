# Rules of Survival (RoS) - Offline Emulator Server & Client Injector

An offline server emulator and injection framework for **Rules of Survival (PC Client)**.

---

## 🌟 Features

- **WebStub Server:** Emulates NetEase HTTP/HTTPS endpoints (`HTTP 80` & `HTTPS 443`) for version checks, patch skipping, and DNS resolution.
- **LoginApp Server:** UDP server (`Port 20013`) handling client handshake, RSA key exchange, and BaseApp redirection.
- **BaseApp Server:** UDP server (`Port 20015`) managing player entities, character data, inventory, and lobby synchronization.
- **Session & Matchmaking:** Per-player Blowfish sessions and a configurable Battle Royale room queue, countdown, and spawn assignment.
- **Battle Simulation:** Server-authoritative movement, loot pickup, damage, safe-zone ticks, and winner detection.
- **SQLite Persistence:** Accounts, loadouts, and match statistics in `data/ros_server.db`, with one-time import from an existing `data/accounts.json`.
- **Leaderboard:** JSON results at `http://127.0.0.1:80/api/leaderboard`.
- **Client Hook & Injector (Frida):** Dynamic memory hook attaching to `ros.exe` to bypass encryption filters and inject custom Python hooks (`login_fix_hall.py`).
- **Account & Character Manager:** Interactive CLI launcher supporting Quick Login, Registration, Multiple Accounts, and automated session syncing to SQLite.
- **Centralized Configuration:** One-click configuration via `config.json` for paths, ports, server IPs, and host bindings.
- **NPK Studio GUI:** Built-in tool in `tools/npk_gui.py` to inspect, unpack, and view game NPK assets.

---

## 📋 Requirements & Prerequisites

1. **Operating System:** Windows 10 / 11 (64-bit)
2. **Python:** Python 3.10, 3.11, or 3.12
   - ⚠️ *Make sure to check **"Add Python to PATH"** during Python installation.*
3. **Administrator Privileges:**
   - Required to bind ports `80` & `443` (HTTP/HTTPS) and allow Frida to attach to `ros.exe`.
4. **RoS PC Game Client:**
   - Clean Rules of Survival PC client folder containing `ros.exe`.

---

## 🚀 Quick Setup & Installation

### Step 1: Clone the Repository
```bash
git clone https://github.com/aqli-project/Ros-Emulator.git
cd Ros-Emulator
```

### Step 2: Install Python Dependencies
Open PowerShell or Command Prompt as **Administrator** and run:
```bash
pip install -r requirements.txt
```

### Step 3: Configure `config.json`
Open `config.json` in the root folder and configure your game directory and server IP:
```json
{
  "game_directory": "D:\\Game\\RosOfflineReborn",
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
```

- **`game_directory`**: Path to your RoS game client folder (where `ros.exe` is located).
- **`server_host`**: Set to `127.0.0.1` for single-player offline mode, or your LAN/Public IP for multiplayer network play.
- **`server_name`**: Server name displayed on the in-game login screen.

---

## 🎮 Running the Game & Server

### Option A: One-Click Launch (Recommended)
Simply **right-click and Run as Administrator** (or double-click):
```
launch_client.bat
```
This batch script will automatically:
1. Elevate to Administrator privileges.
2. Check and start the Emulator Server (`run_server.py`) in the background if not already running.
3. Open the Account Manager CLI (Select account, Register, or Quick Login).
4. Launch the Frida Client Hook & Injector agent.
5. Launch `ros.exe` and automatically synchronize character progress upon exiting.

---

### Option B: Manual / Standalone Commands

#### 1. Run Dedicated Emulator Server:
```bash
python run_server.py
```

#### 2. Run Interactive Client Launcher & Account Manager:
```bash
python launch_client.py
```

#### 3. Run Client Injector Agent Standalone:
```bash
python client_injector.py
```

#### 4. Launch NPK Asset Studio (GUI Tool):
```bash
python tools/npk_gui.py
```

#### 5. Verify concurrent sessions and matchmaking without `ros.exe`:
Start the server in one terminal, then run:
```bash
python test_client.py --multi
```
The test starts two independent UDP clients, logs both in, queues them, and checks that they reach the same `IN_PROGRESS` room with separate spawn coordinates.

Room settings can be changed in `config.json` or with `ROS_ROOM_MAP`, `ROS_ROOM_MAX_PLAYERS`, `ROS_ROOM_MIN_PLAYERS`, and `ROS_ROOM_COUNTDOWN_SECONDS`.

---

## 🏗️ Architecture Overview

```
                      +-----------------------------+
                      |       RoS Game Client       |
                      |          (ros.exe)          |
                      +--------------+--------------+
                                     |
              +----------------------+----------------------+
              |                      |                      |
     [HTTP/HTTPS 80/443]       [UDP 20013]            [UDP 20015]
              v                      v                      v
     +-----------------+    +-----------------+    +-----------------+
     | WebStub Server  |    | LoginApp Server |    | BaseApp Server  |
     | (Auth/DNS/CDN)  |    | (Handshake/RSA) |    | (Lobby/Player)  |
     +-----------------+    +-----------------+    +-----------------+
              ^                      ^                      ^
              +----------------------+----------------------+
                                     |
                        +------------+------------+
                        | Frida Client Injector   |
                        | (PyRun login_fix_hall)  |
                        +-------------------------+
                                     |
                        +------------+------------+
                        |  Account & Data Store   |
                        | (SQLite + legacy JSON)  |
                        +-------------------------+
```

---

## 📂 Project Structure

```
.
├── config.json            # Central configuration (game path, server IP, ports)
├── config.prod.example.json # Production/VPS configuration template
├── requirements.txt       # Python dependencies
├── launch_client.bat      # 1-Click Game & Server Launcher
├── launch_client.py       # Interactive Account Manager & Game Runner
├── start_server.bat       # Standalone Server Launcher
├── run_server.py          # Master Emulator Server Runner
├── client_injector.py     # Frida Memory Hook & Injection Agent
├── account_manager.py     # Account CRUD & user_info.txt Sync
├── certs/                 # SSL/TLS Certificates for HTTPS WebStub
├── common/                # Shared Crypto, Blowfish, Logger & Mercury Packets
├── config/                # Settings Loader & Path Configuration
├── crypto/                # Blowfish Keys & RSA Keypairs
├── data/                  # SQLite database and legacy JSON migration source
├── deploy/                # Firewall rule helpers for Linux and Windows
├── schemas/               # Entity & Avatar Base Stream Schemas
├── services/              # WebStub, LoginApp, and BaseApp Services
└── tools/                 # NPK Studio GUI & Asset Decoders
```

---

## ❓ Troubleshooting & FAQ

1. **Port 80 or 443 already in use:**
   - Ensure IIS, Apache, Nginx, or Skype/VMware services occupying port 80/443 are stopped (`netstat -ano | findstr :80`).
2. **Frida Access Denied / VirtualAllocEx error:**
   - Run Command Prompt / PowerShell as **Administrator**.
   - Make sure your antivirus is not blocking Frida injection.
3. **Character not saving:**
   - Close the game normally so `launch_client.py` can capture the process exit event and save character updates to SQLite.

---

## 🌐 Singapore VPS Deployment

This emulator is intended for educational/testing use; exposing it publicly is not a substitute for a hardened production game service. Use a dedicated host, keep the operating system and Python dependencies updated, and restrict administrative access separately. Do not copy test accounts or development credentials to a public host.

1. Copy `config.prod.example.json` to `config.json` and set `public_host` to the VPS public IPv4 address advertised to clients. Existing configurations may continue using `server_host`; `public_host` takes precedence. `bind_host` should remain `0.0.0.0` so services accept traffic on the external interface. Keep `room_max_players`, `room_min_players`, and `room_countdown_seconds` appropriate for your test population.
2. Install the requirements, then run `python run_server.py` from the repository directory. The account database is created at `data/ros_server.db`; retain that file and its SQLite WAL files while the server is running. Existing `data/accounts.json` is imported once and is not deleted.
3. Allow these exact inbound ports in both the host firewall and the VPS provider's cloud firewall/security group:

   | Port | Protocol | Purpose |
   |---|---|---|
   | 80 | TCP | WebStub HTTP |
   | 443 | TCP | WebStub HTTPS (only active when TLS certificates are present) |
   | 20013 | UDP | LoginApp |
   | 20015 | UDP | BaseApp |

4. On Ubuntu with UFW, review and run `sudo sh deploy/allow-ros-ports-ufw.sh`. On Windows Server, open an elevated PowerShell and run `.\deploy\allow-ros-ports-windows.ps1`. These scripts add inbound allow rules for only the ports listed above; configure equivalent rules in the VPS provider firewall.
5. Test from another machine using `python test_client.py --host <VPS_PUBLIC_IPV4> --battle`. Verify that `/api/leaderboard` responds over HTTP and that both UDP services are reachable. Configure valid certificates for HTTPS before relying on port 443.

The local template uses loopback as its public address; that value is not suitable for remote clients. Port 80/443 may already be occupied by another web server. The server requires access to the configured bind ports, and public UDP reachability must be verified at both host and provider-firewall layers.

---

## 📄 License & Disclaimer

This project is created for educational, research, and preservation purposes only. Rules of Survival and all associated assets are property of NetEase Games.
