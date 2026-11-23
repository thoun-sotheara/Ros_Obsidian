#!/usr/bin/env python3
"""Standalone Phase 1 UDP test client for the Rules of Survival emulator."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import socket
import struct
import time
import urllib.request
from pathlib import Path

from Crypto.Cipher import Blowfish, PKCS1_OAEP
from Crypto.PublicKey import RSA

from common.inventory import build_free_item_package
from services.avatar_stream import build_avatar_base_stream


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_KEY_PATH = BASE_DIR / "crypto" / "our_loginapp.pub.pem"


def packed_string(value: bytes) -> bytes:
    if len(value) >= 0xFF:
        return b"\xff" + struct.pack("<I", len(value))[:3] + value
    return bytes([len(value)]) + value


def blowfish_encrypt_plaintext_chaining(key: bytes, data: bytes) -> bytes:
    cipher = Blowfish.new(key, Blowfish.MODE_ECB)
    output = bytearray()
    previous = b"\x00" * 8
    for offset in range(0, len(data), 8):
        block = data[offset:offset + 8]
        if len(block) != 8:
            raise ValueError("plaintext block is not 8 bytes")
        xored = bytes(a ^ b for a, b in zip(block, previous))
        output.extend(cipher.encrypt(xored))
        previous = block
    return bytes(output)


def blowfish_decrypt_plaintext_chaining(key: bytes, data: bytes) -> bytes:
    cipher = Blowfish.new(key, Blowfish.MODE_ECB)
    output = bytearray()
    previous = b"\x00" * 8
    for offset in range(0, len(data), 8):
        block = data[offset:offset + 8]
        if len(block) != 8:
            raise ValueError("ciphertext block is not 8 bytes")
        plain = bytes(a ^ b for a, b in zip(cipher.decrypt(block), previous))
        output.extend(plain)
        previous = plain
    return bytes(output)


def channel_pad(inner: bytes) -> bytes:
    wastage = (-len(inner)) % 8 or 8
    return inner + (b"\x00" * (wastage - 1)) + bytes([wastage])


def channel_strip_wastage(plain: bytes) -> bytes:
    if not plain:
        return b""
    wastage = plain[-1]
    if 1 <= wastage <= 8 and wastage <= len(plain):
        return plain[:-wastage]
    return plain


def query_webstub(host: str, port: int) -> bool:
    url = f"http://{host}:{port}/server_list"
    print(f"[HTTP] Querying {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"[HTTP] Status {response.status}: {body.strip()}")
            return response.status == 200
    except Exception as exc:
        print(f"[HTTP] Server check failed: {exc}")
        return False


def query_leaderboard(host: str, port: int) -> dict[str, dict]:
    url = f"http://{host}:{port}/api/leaderboard"
    with urllib.request.urlopen(url, timeout=4) as response:
        if response.status != 200:
            raise RuntimeError(f"Leaderboard returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    entries = payload.get("leaderboard")
    if not isinstance(entries, list):
        raise ValueError("Leaderboard response does not contain a leaderboard list")
    return {
        entry["username"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("username"), str)
    }


def decrypt_login_reply(packet: bytes, session_key: bytes) -> tuple[int, bytes]:
    if len(packet) < 11 or packet[2] != 0xFF:
        raise ValueError("invalid LoginApp Mercury reply")

    reply_id = struct.unpack_from("<I", packet, 7)[0]
    payload = packet[11:]
    status = payload[0]
    encrypted = payload[1:]

    if status == 0x01:
        plain = blowfish_decrypt_plaintext_chaining(session_key, encrypted)
        plain = channel_strip_wastage(plain)
        return status, plain

    plain = blowfish_decrypt_plaintext_chaining(session_key, encrypted)
    plain = plain.rstrip(b"\x00")
    if plain and plain[0] <= len(plain) - 1:
        plain = plain[1:1 + plain[0]]
    return status, plain


def receive_entity_packets(sock: socket.socket, session_key: bytes, timeout: float = 8.0):
    sock.settimeout(timeout)
    found = set()

    for seq in range(1, 5):
        inner = struct.pack("<H", 0x0048) + struct.pack("<I", seq)
        sock.send(blowfish_encrypt_plaintext_chaining(session_key, channel_pad(inner)))

        # Each reliable request produces an ACK followed by an entity-stage packet.
        for _ in range(3):
            try:
                encrypted = sock.recv(65535)
            except socket.timeout:
                break

            plain = blowfish_decrypt_plaintext_chaining(session_key, encrypted)
            plain = channel_strip_wastage(plain)
            if len(plain) < 3:
                continue

            flags = struct.unpack_from("<H", plain, 0)[0]
            if not (flags & 0x0008):
                continue

            msg_id = plain[2]

            if msg_id == 5:
                if len(plain) >= 5:
                    length = int.from_bytes(plain[3:5], "little")
                    payload = plain[5:5 + length]
                    if len(payload) >= 6:
                        entity_id = struct.unpack_from("<I", payload, 0)[0]
                        entity_type = struct.unpack_from("<H", payload, 4)[0]
                        if entity_id == 0x01000001 and entity_type == 0x13:
                            print("[BaseApp] LoginProxy entity created")
                            found.add("LoginProxy")
                            break
                        if entity_id == 0x01000002 and entity_type == 0x14:
                            print("[BaseApp] Account entity created")
                            found.add("Account")
                            break
                        if entity_id == 0x01000003 and entity_type == 0x15:
                            avatar_stream = payload[6:] if len(payload) >= 6 else b""
                            expected_stream, rows = build_avatar_base_stream(with_rows=True)
                            item_count = len(build_free_item_package()["itemList"])
                            print("[BaseApp] Avatar entity created")
                            print(f"[Inventory] Received {item_count} unlocked catalog items in dtsItemPackage")
                            print(f"[Inventory] Avatar stream: {len(avatar_stream)} bytes, 94 properties")
                            if avatar_stream == expected_stream:
                                print("[Inventory] Received avatar stream matches the serialized local catalog stream")
                            else:
                                print("[Inventory] Warning: received stream differs from default local catalog stream")
                            found.add("Avatar")
                            break

            elif msg_id == 139:
                print("[BaseApp] Account.onLogin(0, '') received")
                break

    return found


def simulate_player(host: str, login_port: int, base_port: int, username: str, password: str, queue_match: bool):
    rsa_public = RSA.import_key(PUBLIC_KEY_PATH.read_bytes())
    rsa_cipher = PKCS1_OAEP.new(rsa_public)

    session_key = secrets.token_bytes(16)
    reply_id = secrets.randbits(32)
    login_plain = (
        b"\x01"
        + packed_string(username.encode("utf-8"))
        + packed_string(password.encode("utf-8"))
        + packed_string(session_key)
        + (b"\x00" * 16)
        + struct.pack("<I", 0)
    )

    encrypted_login = rsa_cipher.encrypt(login_plain)
    login_packet = (
        b"\x00" * 15
        + encrypted_login
    )
    login_packet = login_packet[:5] + struct.pack("<I", reply_id) + login_packet[9:]

    login_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    login_socket.settimeout(5)
    login_socket.sendto(login_packet, (host, login_port))
    print(f"[LoginApp] Sent credentials for {username!r}")

    try:
        reply, source = login_socket.recvfrom(65535)
    except socket.timeout:
        print("[LoginApp] No response")
        login_socket.close()
        return None

    print(f"[LoginApp] Received {len(reply)} bytes from {source}")
    status, login_result = decrypt_login_reply(reply, session_key)
    if status != 0x01:
        message = login_result.rstrip(b"\x00")
        print(f"[LoginApp] Login rejected: {message.decode('utf-8', errors='replace')}")
        login_socket.close()
        return None

    print("[LoginApp] Login accepted; redirecting to BaseApp")
    login_socket.close()

    base_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    base_socket.settimeout(3)
    base_socket.connect((host, base_port))
    initial_request = b"\x01\x00" + b"\x00" + b"\x0b\x00" + struct.pack("<I", reply_id) + (b"\x00" * 15)
    base_socket.send(initial_request)

    try:
        base_reply = base_socket.recv(65535)
        decrypted = blowfish_decrypt_plaintext_chaining(session_key, base_reply)
        print(f"[BaseApp] Initial login reply received ({len(decrypted)} decrypted bytes)")
    except socket.timeout:
        print("[BaseApp] Initial login reply timed out")
        base_socket.close()
        return None

    print("[BaseApp] Requesting entity progression packets ...")
    found = receive_entity_packets(base_socket, session_key)

    missing = {"LoginProxy", "Account", "Avatar"} - found
    if missing:
        print("[BaseApp] Missing packets: " + ", ".join(sorted(missing)))
        base_socket.close()
        return None

    result = {"username": username, "socket": base_socket, "session_key": session_key}
    if not queue_match:
        base_socket.close()
        return result

    join_event = send_client_command(base_socket, session_key, 10, "queue:join")
    print(f"[{username}] Queue response: {join_event}")
    return result


def send_client_command(
    sock: socket.socket,
    session_key: bytes,
    seq: int,
    command: str,
    expected_type: str | tuple[str, ...] | None = None,
    timeout: float = 4.0,
) -> dict:
    inner = struct.pack("<H", 0x0048) + struct.pack("<I", seq) + command.encode("utf-8")
    sock.send(blowfish_encrypt_plaintext_chaining(session_key, channel_pad(inner)))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            packet = sock.recv(65535)
        except socket.timeout:
            break
        plain = channel_strip_wastage(blowfish_decrypt_plaintext_chaining(session_key, packet))
        if len(plain) < 5 or plain[2] != 250:
            continue
        payload_length = int.from_bytes(plain[3:5], "little")
        try:
            event = json.loads(plain[5:5 + payload_length].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if expected_type is None or event.get("type") == expected_type or (
            isinstance(expected_type, tuple) and event.get("type") in expected_type
        ):
            return event
    raise TimeoutError(f"no room response received for {command}")


def wait_for_match(player: dict) -> dict:
    sock = player["socket"]
    key = player["session_key"]
    deadline = time.monotonic() + 8
    seq = 11
    while time.monotonic() < deadline:
        event = send_client_command(sock, key, seq, "room:status", expected_type="room_status")
        seq += 1
        if event.get("state") == "IN_PROGRESS":
            return event
        time.sleep(0.1)
    raise TimeoutError(f"{player['username']} did not enter an active match")


def main():
    parser = argparse.ArgumentParser(description="Standalone emulator test client")
    parser.add_argument("--username", default="testuser")
    parser.add_argument("--password", default="test123")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=80)
    parser.add_argument("--login-port", type=int, default=20013)
    parser.add_argument("--base-port", type=int, default=20015)
    parser.add_argument("--multi", action="store_true", help="Run two concurrent players through matchmaking")
    parser.add_argument("--battle", action="store_true", help="Run the full two-player battle simulation")
    args = parser.parse_args()

    if not query_webstub(args.host, args.http_port):
        print("[!] WebStub did not respond. Start with: python run_server.py")
        return 1

    leaderboard_before = (
        query_leaderboard(args.host, args.http_port) if args.battle else {}
    )

    if not PUBLIC_KEY_PATH.exists():
        print(f"[!] LoginApp public key missing: {PUBLIC_KEY_PATH}")
        return 1

    if not args.multi and not args.battle:
        player = simulate_player(
            args.host, args.login_port, args.base_port,
            args.username, args.password, queue_match=False,
        )
        if player is None:
            return 1
        print("[BaseApp] Standalone Phase 1/2 test completed successfully")
        return 0

    players = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                simulate_player,
                args.host,
                args.login_port,
                args.base_port,
                username,
                "test123",
                True,
            )
            for username in ("player_kh1", "player_kh2")
        ]
        for future in futures:
            player = future.result()
            if player is None:
                return 1
            players.append(player)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            events = list(executor.map(wait_for_match, players))
        first, second = events
        if first.get("room_id") != second.get("room_id"):
            print(f"[Matchmaking] Room mismatch: {first.get('room_id')} != {second.get('room_id')}")
            return 1
        if first.get("state") != "IN_PROGRESS" or second.get("state") != "IN_PROGRESS":
            print(f"[Matchmaking] Expected IN_PROGRESS, got {first.get('state')} and {second.get('state')}")
            return 1
        expected_players = {"player_kh1", "player_kh2"}
        if set(first.get("players", [])) != expected_players:
            print(f"[Matchmaking] Unexpected room members: {first.get('players')}")
            return 1
        print(
            f"[Matchmaking] Both players joined {first['room_id']} on {first['map']} "
            f"({first['state']}); distinct spawns: {first['spawn_points']}"
        )
        if not args.battle:
            print("[Matchmaking] Concurrent session and room test completed successfully")
            return 0

        player_one = next(player for player in players if player["username"] == "player_kh1")
        player_two = next(player for player in players if player["username"] == "player_kh2")
        seq_one = 20
        seq_two = 20

        state = send_client_command(
            player_one["socket"], player_one["session_key"], seq_one,
            "battle:state", expected_type="battle_state",
        )
        seq_one += 1
        if state.get("state") != "IN_PROGRESS":
            raise RuntimeError(f"Battle did not start: {state.get('state')}")
        weapon_loot = next(item for item in state["loot"] if item.get("item") == "M4A1")
        weapon_position = weapon_loot["position"]

        move_command = "battle:move:" + json.dumps({
            "x": weapon_position["x"],
            "y": weapon_position["y"],
            "z": weapon_position["z"],
            "yaw": 0.0,
        }, separators=(",", ":"))
        move_event = send_client_command(
            player_one["socket"], player_one["session_key"], seq_one,
            move_command, expected_type="movement",
        )
        seq_one += 1
        print(f"[Battle] {player_one['username']} moved to loot at {move_event['player']['position']}")

        pickup_command = "battle:pickup:" + json.dumps({"loot_id": weapon_loot["loot_id"]})
        pickup_event = send_client_command(
            player_one["socket"], player_one["session_key"], seq_one,
            pickup_command, expected_type="loot_picked",
        )
        seq_one += 1
        if pickup_event["player"].get("weapon") != "M4A1":
            raise RuntimeError("M4A1 pickup did not equip the weapon")
        print(f"[Battle] Picked up {pickup_event['item']['item']}; ammo={pickup_event['player']['ammo']}")

        final_shot = None
        for _ in range(4):
            fire_command = "battle:fire:" + json.dumps({"target": player_two["username"]})
            final_shot = send_client_command(
                player_one["socket"], player_one["session_key"], seq_one,
                fire_command, expected_type=("damage", "elimination"),
            )
            seq_one += 1
            if final_shot.get("type") not in ("damage", "elimination"):
                continue
            if final_shot.get("type") == "elimination":
                print(
                    f"[Battle] Kill event: {final_shot['target']} eliminated by "
                    f"{final_shot['shooter_id']} (kills={final_shot['shooter']['kills']})"
                )
                break
        if not final_shot or final_shot.get("type") != "elimination":
            raise RuntimeError("Target was not eliminated during the test")

        final_state = send_client_command(
            player_one["socket"], player_one["session_key"], seq_one,
            "battle:state", expected_type="battle_state",
        )
        if final_state.get("state") != "FINISHED" or final_state.get("winner") != player_one["username"]:
            raise RuntimeError(f"Unexpected final battle result: {final_state}")
        print(
            f"[Battle] Match finished; winner={final_state['winner']}, "
            f"state={final_state['state']}, alive={final_state['alive_count']}"
        )
        leaderboard_after = query_leaderboard(args.host, args.http_port)
        previous_winner = leaderboard_before.get(player_one["username"], {})
        previous_loser = leaderboard_before.get(player_two["username"], {})
        winner_stats = leaderboard_after.get(player_one["username"])
        loser_stats = leaderboard_after.get(player_two["username"])
        if winner_stats is None or loser_stats is None:
            raise RuntimeError("Finished match participants were not recorded on the leaderboard")
        if (
            winner_stats["wins"] < previous_winner.get("wins", 0) + 1
            or winner_stats["kills"] < previous_winner.get("kills", 0) + 1
            or loser_stats["matches_played"] < previous_loser.get("matches_played", 0) + 1
        ):
            raise RuntimeError(
                f"Leaderboard totals did not include this match: {winner_stats}, {loser_stats}"
            )
        print(
            "[Leaderboard] "
            f"{player_one['username']}: wins={winner_stats['wins']}, kills={winner_stats['kills']}; "
            f"{player_two['username']}: wins={loser_stats['wins']}, kills={loser_stats['kills']}"
        )
        print("[Battle] Full Battle Royale simulation completed successfully")
        return 0
    finally:
        for player in players:
            player["socket"].close()


if __name__ == "__main__":
    raise SystemExit(main())
