import os
import sys
import time
import socket
import subprocess
import ctypes
from pathlib import Path

import account_manager
from config.settings import CLIENT_DIR as GAME_DIR, BASE_DIR as SERVER_DIR, PUBLIC_HOST, SERVER_NAME

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_if_needed():
    if not is_admin():
        print("[*] Administrator privileges required. Elevating...")
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            f'"{os.path.abspath(__file__)}"',
            str(SERVER_DIR),
            1
        )
        sys.exit(0)

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    print("=" * 66)
    print(r"""  ____  _   _ _     _____ ____     ___  _____   ______  ______ _____ 
 |  _ \| | | | |   | ____/ ___|   / _ \|  ___| / ___\ \/ / ___| ____|
 | |_) | | | | |   |  _| \___ \  | | | | |_   | |    \  /\___ \  _|  
 |  _ <| |_| | |___| |___ ___) | | |_| |  _|  | |___ /  \ ___) | |___ 
 |_| \_\\___/|_____|_____|____/   \___/|_|     \____/_/\_\____/|_____|
                     CLIENT LAUNCHER & ACCOUNT                       """)
    print("=" * 66)

def check_server_port(port=80, host="127.0.0.1"):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((host, port))
            return True
    except Exception:
        return False

def ensure_server_running():
    print("[*] Checking server emulator status (port 80/443)...")
    if not check_server_port(80):
        print("[!] Server is not running! Starting server emulator in a new window...")
        server_script = SERVER_DIR / "run_server.py"
        subprocess.Popen(
            [sys.executable, str(server_script)],
            cwd=str(SERVER_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        for _ in range(6):
            time.sleep(1)
            if check_server_port(80):
                break
        if check_server_port(80):
            print("[+] Server emulator started successfully.")
        else:
            print("[*] Server is starting in a separate window.")
    else:
        print("[+] Server emulator is active.")

def drop_skip_patch_markers():
    markers = [
        GAME_DIR / "no_patch.txt",
        GAME_DIR / "no_first_patch.txt",
        GAME_DIR / "Documents" / "no_patch.txt",
        GAME_DIR / "Documents" / "no_first_patch.txt",
    ]
    for m in markers:
        try:
            m.parent.mkdir(parents=True, exist_ok=True)
            if not m.exists():
                m.touch()
        except Exception:
            pass

def select_or_create_account():
    while True:
        clear_screen()
        print_banner()
        last_acc = account_manager.get_last_account()
        last_str = ""
        if last_acc:
            nick = last_acc.get("nickname") or "(No character name)"
            last_str = f" [User: {last_acc['username']} | Character: {nick}]"

        print(f" [1] Quick Login{last_str} (Press ENTER)")
        print(" [2] Login Other Account (ID & Password)")
        print(" [3] Create New Account (Register ID & Password)")
        print(" [4] Manage Accounts (View All / Delete)")
        print(" [0] Exit")
        print("=" * 66)

        choice = input(" Option [1]: ").strip()
        if choice == "" or choice == "1":
            if last_acc:
                return last_acc
            else:
                print("\n[!] No saved accounts found. Please register a new account.")
                time.sleep(1.5)
                continue

        elif choice == "2":
            clear_screen()
            print_banner()
            print(" --- ACCOUNT LOGIN ---")
            username = input(" Enter Username / ID: ").strip()
            password = input(" Enter Password     : ").strip()
            acc, msg = account_manager.authenticate(username, password)
            if acc:
                print(f"\n[+] Successfully logged in as '{acc['username']}'!")
                time.sleep(1)
                return acc
            elif msg == "Account not found!":
                print(f"\n[?] ID '{username}' is not registered.")
                create_now = input(" Register this new account now? [Y/n]: ").strip().lower()
                if create_now in ("", "y", "ya", "yes"):
                    acc, reg_msg = account_manager.register(username, password)
                    if acc:
                        print(f"\n[+] Account '{acc['username']}' registered and logged in successfully!")
                        time.sleep(1.5)
                        return acc
                    else:
                        print(f"\n[!] Failed to create account: {reg_msg}")
                        input(" Press ENTER to go back...")
                else:
                    continue
            else:
                print(f"\n[!] Login failed: {msg}")
                input(" Press ENTER to go back...")

        elif choice == "3":
            clear_screen()
            print_banner()
            print(" --- CREATE NEW ACCOUNT ---")
            username = input(" Create Username / ID (min 3 chars): ").strip()
            password = input(" Create Password     (min 3 chars): ").strip()
            nickname = input(" Character Nickname (Optional, can set in game): ").strip()

            acc, msg = account_manager.register(username, password, nickname)
            if acc:
                print(f"\n[+] Account '{acc['username']}' created successfully!")
                time.sleep(1)
                return acc
            else:
                print(f"\n[!] Failed to create account: {msg}")
                input(" Press ENTER to go back...")

        elif choice == "4":
            manage_accounts()

        elif choice == "0":
            sys.exit(0)

def manage_accounts():
    while True:
        clear_screen()
        print_banner()
        print(" --- SAVED ACCOUNTS LIST ---")
        data = account_manager.load_accounts_data()
        accounts = data.get("accounts", {})
        if not accounts:
            print(" No accounts found.")
        else:
            for idx, (u, a) in enumerate(accounts.items(), 1):
                nick = a.get("nickname") or "(No character name)"
                role_id = a.get("role_id", "-")
                status = "Lobby Ready" if a.get("created") and a.get("nickname") else "New Character"
                print(f" {idx}. ID: {u:<12} | Nickname: {nick:<14} | RoleID: {role_id} [{status}]")

        print("-" * 66)
        print(" [D] Delete Account")
        print(" [B] Back to Main Menu")
        sub_ch = input(" Option: ").strip().lower()
        if sub_ch == "b" or sub_ch == "":
            break
        elif sub_ch in ("d", "h"):
            u_del = input(" Enter the account ID to delete: ").strip()
            if account_manager.delete_account(u_del):
                print(f"[+] Account '{u_del}' deleted successfully.")
            else:
                print(f"[!] Account '{u_del}' not found.")
            time.sleep(1.5)

def main():
    elevate_if_needed()

    account = select_or_create_account()
    if not account:
        return

    clear_screen()
    print_banner()
    username = account["username"]
    nickname = account.get("nickname", "")
    has_character = bool(account.get("created") and nickname)

    # Determine fallback mode:
    # If character already exists, load directly into Main Lobby (uimain)!
    # If new account, load into Character Creation screen (select)!
    fallback_mode = "uimain" if has_character else "select"

    print(f"[*] Active Account : {username}")
    print(f"[*] Nickname       : {nickname or '(New Character - Set name in game)'}")
    print(f"[*] Server Name    : {SERVER_NAME} ({PUBLIC_HOST})")
    print(f"[*] Entry Mode     : {'MAIN LOBBY (Direct Entry)' if fallback_mode == 'uimain' else 'CHARACTER CREATION (Set Name)'}")
    print("=" * 66)

    # 1. Sync account info to user_info.txt
    print("[*] Preparing character data file...")
    account_manager.sync_to_game(account)

    # 2. Drop skip patch markers
    drop_skip_patch_markers()

    # 3. Ensure server is up
    ensure_server_running()

    # 4. Prepare environment variables for ros.exe & python scripts
    game_env = os.environ.copy()
    game_env["ROS_USERNAME"] = username
    game_env["ROS_SERVER_NAME"] = SERVER_NAME
    game_env["ROS_PUBLIC_HOST"] = PUBLIC_HOST
    game_env["ROS_CLIENT_DIR"] = str(GAME_DIR)
    game_env["ROS_CLIENT_FALLBACK"] = fallback_mode
    game_env["ROS_CLIENT_FALLBACK_DELAY"] = "15"

    # 5. Start Frida Client Injector in dedicated console
    print("[*] Launching Client Hook & Injector (Frida)...")
    injector_script = SERVER_DIR / "client_injector.py"
    injector_proc = subprocess.Popen(
        [sys.executable, str(injector_script)],
        cwd=str(SERVER_DIR),
        env=game_env,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    # 6. Launch ros.exe
    exe_path = GAME_DIR / "ros.exe"
    if not exe_path.exists():
        print(f"[!] Game client executable not found: {exe_path}")
        input("Press ENTER to exit...")
        return

    print("[*] Launching ros.exe...")
    game_process = subprocess.Popen([str(exe_path)], cwd=str(GAME_DIR), env=game_env)

    print("\n" + "=" * 66)
    print(" [+] Game client launched successfully!")
    print(f" [+] In-game server name: '{SERVER_NAME}' ({PUBLIC_HOST})")
    print("=" * 66)
    print(" [i] IMPORTANT: When the game login screen appears:")
    print("     Wait about 5 seconds until 'ROS Client Injector' window")
    print("     displays '[+] CLIENT READY!', then click the PLAY button!")
    print("=" * 66)
    print("\n[*] Waiting for game session to end (auto-save active)...")

    # Monitor game process and auto-save on exit
    try:
        game_process.wait()
    except KeyboardInterrupt:
        pass

    # Ensure injector closes if game closes
    try:
        if injector_proc.poll() is None:
            injector_proc.terminate()
    except Exception:
        pass

    print("\n[*] Game closed. Synchronizing character data to database...")
    account_manager.sync_from_game(username)
    updated = account_manager.get_account(username)
    new_nick = updated.get("nickname", "") if updated else ""
    print(f"[+] Done! Account '{username}' (Character: '{new_nick}') saved successfully.")
    time.sleep(2)

if __name__ == "__main__":
    main()
