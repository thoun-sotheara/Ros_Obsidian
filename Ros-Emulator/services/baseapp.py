import json
import socket
import struct
import threading
import time
from Crypto.Cipher import Blowfish

from config.settings import BIND_HOST, BASEAPP_PORT
from common.logger import ServerLogger
from common.session_manager import PlayerSession, SESSION_MANAGER
from common.room_manager import ROOM_MANAGER
from common.room_manager import IN_PROGRESS
from common.battle_engine import BATTLE_ENGINE
from services.avatar_stream import build_avatar_base_stream
import account_manager

logger = ServerLogger("BASEAPP")

class SessionCipher:
    def __init__(self, key: bytes):
        self.ecb = Blowfish.new(key, Blowfish.MODE_ECB)

    def encrypt_cbc_iv0(self, data: bytes) -> bytes:
        out = bytearray()
        prev = b"\x00" * 8
        for i in range(0, len(data), 8):
            blk = data[i:i + 8]
            out += self.ecb.encrypt(bytes(a ^ b for a, b in zip(blk, prev)))
            prev = blk
        return bytes(out)

    def decrypt_cbc_iv0(self, data: bytes) -> bytes:
        out = bytearray()
        prev = b"\x00" * 8
        for i in range(0, len(data), 8):
            blk = data[i:i + 8]
            p = bytes(a ^ b for a, b in zip(self.ecb.decrypt(blk), prev))
            out += p
            prev = p
        return bytes(out)

class BaseAppServer:
    def __init__(self, host: str = BIND_HOST, port: int = BASEAPP_PORT):
        self.host = host
        self.port = port
        self.running = False
        self.sock = None
        self.thread = None
        self.keepalive_thread = None

        self.chan_seq = 0
        self.client_stages = {}

        # Entity IDs
        self.BASE_EID = 0x01000001
        self.ACCOUNT_EID = 0x01000002
        self.AVATAR_EID = 0x01000003

        # Entity Types
        self.TYPE_LOGINPROXY = 0x13
        self.TYPE_ACCOUNT = 0x14
        self.TYPE_AVATAR = 0x15
        ROOM_MANAGER.set_transition_callback(self._on_room_transition)

    @staticmethod
    def _channel_cipher(address: tuple[str, int]) -> SessionCipher | None:
        session = SESSION_MANAGER.get_by_address(address)
        if session is None or not session.blowfish_key:
            return None
        return SessionCipher(session.blowfish_key)

    def channel_encrypt_plain(self, inner: bytes, address: tuple[str, int]) -> bytes:
        """BigWorld plaintext-chaining Blowfish CBC (IV=0) with wastage padding."""
        cipher = self._channel_cipher(address)
        if not cipher:
            raise ValueError(f"No active player session for {address}")

        L = len(inner)
        cl = (-L) % 8 or 8  # wastage count 1..8
        plain = inner + (b"\x00" * (cl - 1)) + bytes([cl])
        return cipher.encrypt_cbc_iv0(plain)

    def channel_decrypt_plain(self, blob: bytes, address: tuple[str, int]) -> bytes | None:
        """Decrypt incoming client channel packet and strip wastage padding."""
        cipher = self._channel_cipher(address)
        if not cipher or len(blob) % 8 != 0:
            return None

        try:
            plain = cipher.decrypt_cbc_iv0(blob)
        except Exception:
            return None

        cl = plain[-1]
        if not (1 <= cl <= 8) or cl >= len(plain):
            return None
        return plain[:-cl]

    def build_ack(self, seq: int, address: tuple[str, int]) -> bytes:
        """Minimal Mercury ACK: flags=0x000C, footer=[seq u32][ackCount=1]."""
        footer = struct.pack("<I", seq & 0xFFFFFFFF) + bytes([1])
        inner = struct.pack("<H", 0x000C) + footer
        return self.channel_encrypt_plain(inner, address)

    def channel_msg(self, msgid: int, payload: bytes = b"", width: int = 2, address: tuple[str, int] | None = None) -> bytes:
        """Construct on-channel downstream message."""
        if address is None:
            raise ValueError("client address is required for encrypted channel messages")
        flags = 0x08  # ON_CHANNEL
        lenfield = struct.pack("<I", len(payload))[:width]
        inner = struct.pack("<H", flags) + bytes([msgid & 0xFF]) + lenfield + payload
        return self.channel_encrypt_plain(inner, address)

    def entity_method(self, entity_id: int, method_index: int, args: bytes = b"", address: tuple[str, int] | None = None) -> bytes:
        """Invoke an entity exposed client method: msgid = 128 + method_index."""
        msgid = 128 + method_index
        width = 2 if msgid <= 190 else 1
        payload = struct.pack("<I", entity_id) + args
        return self.channel_msg(msgid, payload, width, address)

    def push_create_base_player(self, addr: tuple[str, int], entity_id: int, entity_type: int, stream: bytes = b""):
        """Deliver createBasePlayer (channel msgid 5)."""
        payload = struct.pack("<IH", entity_id, entity_type) + stream
        pkt = self.channel_msg(5, payload, width=2, address=addr)
        self.sock.sendto(pkt, addr)
        logger.info(f"Pushed createBasePlayer: EID=0x{entity_id:08X}, Type=0x{entity_type:02X}, stream_len={len(stream)}B -> {addr}")

    def push_login_progression(self, addr: tuple[str, int]):
        """Advance client through login entity lifecycle."""
        stage = self.client_stages.get(addr, 0)

        if stage == 0:
            # Stage 1: Create LoginProxy entity
            self.push_create_base_player(addr, self.BASE_EID, self.TYPE_LOGINPROXY, b"")
            self.client_stages[addr] = 1

        elif stage == 1:
            # Stage 2: Create Account entity
            self.push_create_base_player(addr, self.ACCOUNT_EID, self.TYPE_ACCOUNT, b"")
            self.client_stages[addr] = 2

        elif stage == 2:
            # Stage 3: Call Account.onLogin (method index 11) -> dismisses UILoginLoop
            errcode = struct.pack("<i", 0)  # 0 = SUCCESS
            msg_str = b""
            packed_msg = struct.pack("<B", len(msg_str)) + msg_str
            pkt = self.entity_method(self.ACCOUNT_EID, 11, errcode + packed_msg, addr)
            self.sock.sendto(pkt, addr)
            logger.info(f"Pushed Account.onLogin(0, '') -> {addr}")
            self.client_stages[addr] = 3

        elif stage == 3:
            # Stage 4: Create Avatar entity with full schema properties
            session = SESSION_MANAGER.get_by_address(addr)
            username = session.username if session else ""
            loadout = account_manager.get_loadout(username)
            avatar_stream = build_avatar_base_stream(loadout=loadout)
            self.push_create_base_player(addr, self.AVATAR_EID, self.TYPE_AVATAR, avatar_stream)
            logger.info(f"Pushed Avatar entity into active world -> {addr}")
            self.client_stages[addr] = 4

    def handle_packet(self, data: bytes, addr: tuple[str, int]):
        # Check if it's the raw unencrypted baseapp-login request (24B)
        # 01 00 | 00 | 0b 00 | <replyID u32@5> | ...
        if len(data) >= 9 and data[0:2] in (b"\x01\x00", b"\x00\x01") and data[2] == 0x00:
            reply_id = struct.unpack_from("<I", data, 5)[0]
            session = SESSION_MANAGER.get_by_reply_id(reply_id)
            if session is None:
                session = SESSION_MANAGER.get_by_address(addr)
            if session is None:
                logger.warn(f"Rejected BaseApp connection from {addr}: no matching LoginApp session")
                return
            SESSION_MANAGER.bind_baseapp(session, addr)
            logger.info(f"Received BaseApp initial login request from {addr}, replyID={reply_id}")

            # 32-bit BaseApp login reply candidate:
            # Mercury REPLY message: [0xff][u16 len=8][u32 replyID][u32 newSessionKey]
            # inner Mercury packet: [u16 flags 0x0008] + msg
            body = struct.pack("<I", 0x12345678)
            msg = b"\xff" + struct.pack("<H", 4 + len(body)) + struct.pack("<I", reply_id) + body
            inner = struct.pack("<H", 0x0008) + msg

            enc_reply = self.channel_encrypt_plain(inner, addr)
            self.sock.sendto(enc_reply, addr)
            logger.info(f"Sent BaseApp login reply ({len(enc_reply)}B, replyID={reply_id}) to {addr}")
            return

        # Attempt decryption with the key registered for this client's UDP endpoint.
        session = SESSION_MANAGER.get_by_address(addr)
        if session is None:
            return
        merc = self.channel_decrypt_plain(data, addr)
        if not merc or len(merc) < 2:
            return

        flags = struct.unpack_from("<H", merc, 0)[0]
        is_reliable = bool(flags & 0x0008)
        has_seq = bool(flags & 0x0040)

        seq = None
        if has_seq and len(merc) >= 6:
            seq = struct.unpack_from("<I", merc, 2)[0]

        logger.debug(f"RX Channel packet from {addr}: len={len(merc)}, flags=0x{flags:04X}, seq={seq}, reliable={is_reliable}")

        command_offset = 6 if has_seq else 2
        command = merc[command_offset:] if len(merc) >= command_offset else b""
        command_text = command.decode("utf-8", errors="replace").strip("\x00")
        if command_text.startswith("equip:"):
            try:
                updates = json.loads(command_text[len("equip:"):])
                loadout = account_manager.update_loadout(session.username, updates)
                if loadout is not None:
                    logger.info(f"Saved equip/loadout update for {session.username}: {loadout}")
            except Exception as e:
                logger.warn(f"Invalid equip update: {e}")
        elif command_text == "queue:join":
            try:
                snapshot = ROOM_MANAGER.join(session.username)
                SESSION_MANAGER.set_room(session, snapshot["room_id"])
                self._broadcast_room_update(snapshot)
            except Exception as e:
                logger.error(f"Could not queue {session.username}: {e}")
                self._send_client_event(session, {"type": "error", "message": str(e)})
        elif command_text == "queue:leave":
            snapshot = ROOM_MANAGER.leave(session.username)
            if session.username not in snapshot.get("players", []):
                SESSION_MANAGER.set_room(session, None)
            self._broadcast_room_update(snapshot)
        elif command_text == "room:status":
            snapshot = ROOM_MANAGER.status(session.username)
            self._send_client_event(session, {"type": "room_status", **snapshot})
        elif command_text == "battle:state":
            try:
                self._send_client_event(session, BATTLE_ENGINE.state(self._require_room(session)))
            except ValueError as e:
                self._send_client_event(session, {"type": "error", "message": str(e)})
        elif command_text.startswith("battle:move:"):
            try:
                movement = json.loads(command_text[len("battle:move:"):])
                event = BATTLE_ENGINE.update_position(
                    self._require_room(session),
                    session.username,
                    movement["x"],
                    movement["y"],
                    movement["z"],
                    movement["yaw"],
                )
                self._broadcast_battle_event(event)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                self._send_client_event(session, {"type": "error", "message": str(e)})
        elif command_text.startswith("battle:pickup:"):
            try:
                request = json.loads(command_text[len("battle:pickup:"):])
                event = BATTLE_ENGINE.pickup_loot(
                    self._require_room(session),
                    session.username,
                    str(request["loot_id"]),
                )
                self._broadcast_battle_event(event)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                self._send_client_event(session, {"type": "error", "message": str(e)})
        elif command_text.startswith("battle:fire:"):
            try:
                request = json.loads(command_text[len("battle:fire:"):])
                event = BATTLE_ENGINE.process_fire(
                    self._require_room(session),
                    session.username,
                    str(request["target"]),
                )
                self._broadcast_battle_event(event)
                if event.get("winner"):
                    self._broadcast_battle_event({
                        "type": "match_finished",
                        "room_id": event["room_id"],
                        "state": event["state"],
                        "winner": event["winner"],
                        "alive_count": event["alive_count"],
                    })
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                self._send_client_event(session, {"type": "error", "message": str(e)})

        # If client sent reliable packet, ACK it immediately
        if is_reliable and seq is not None:
            ack_pkt = self.build_ack(seq, addr)
            self.sock.sendto(ack_pkt, addr)
            logger.debug(f"ACKed client reliable packet seq={seq} -> {addr}")

            # Progress entity creation burst on reliable receipts
            self.push_login_progression(addr)

    def _send_client_event(self, session: PlayerSession, event: dict) -> None:
        payload = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
        packet = self.channel_msg(250, payload, width=2, address=session.client_addr)
        self.sock.sendto(packet, session.client_addr)

    @staticmethod
    def _require_room(session: PlayerSession) -> str:
        if not session.room_id:
            raise ValueError("player is not assigned to a match room")
        return session.room_id

    def _on_room_transition(self, snapshot: dict) -> None:
        if snapshot.get("state") == IN_PROGRESS:
            BATTLE_ENGINE.start_room(snapshot)
        self._broadcast_room_update(snapshot)

    def _broadcast_room_update(self, snapshot: dict) -> None:
        event = {"type": "room_update", **snapshot}
        for username in snapshot.get("players", []):
            session = SESSION_MANAGER.get_by_username(username)
            if session is not None and session.connection_state == "BASEAPP_CONNECTED":
                self._send_client_event(session, event)

    def _broadcast_battle_event(self, event: dict) -> None:
        room_id = event.get("room_id")
        for session in SESSION_MANAGER.active_sessions():
            if session.room_id == room_id and session.connection_state == "BASEAPP_CONNECTED":
                self._send_client_event(session, event)

    def _keepalive_loop(self):
        last_keepalive = 0.0
        while self.running:
            time.sleep(1.0)
            if self.sock:
                for event in BATTLE_ENGINE.tick():
                    self._broadcast_battle_event(event)
            if time.monotonic() - last_keepalive < 2.0:
                continue
            last_keepalive = time.monotonic()
            if self.sock:
                for session in SESSION_MANAGER.active_sessions():
                    if session.connection_state != "BASEAPP_CONNECTED":
                        continue
                    try:
                        ack = self.build_ack(0, session.client_addr)
                        self.sock.sendto(ack, session.client_addr)
                    except (OSError, ValueError) as e:
                        logger.warn(f"Could not send keepalive to {session.client_addr}: {e}")

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Fix Windows UDP WSAECONNRESET bug
        try:
            # SIO_UDP_CONNRESET = 0x9800000C
            self.sock.ioctl(0x9800000C, struct.pack("I", 0))
        except Exception:
            pass

        self.sock.bind((self.host, self.port))
        self.running = True
        logger.info(f"Listening on UDP {self.host}:{self.port} (BigWorld BaseApp Channel)")

        self.keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self.keepalive_thread.start()

        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data:
                    continue
                self.handle_packet(data, addr)
            except socket.timeout:
                continue
            except OSError as e:
                # Handle connection reset gracefully on Windows
                if getattr(e, "winerror", None) == 10054:
                    continue
                if self.running:
                    logger.error(f"BaseApp receive error: {e}")
                    time.sleep(0.1)
            except Exception as e:
                if self.running:
                    logger.error(f"BaseApp receive error: {e}")
                    time.sleep(0.1)

    def start(self):
        if self.running:
            return
        self.thread = threading.Thread(target=self.run, name="BaseApp-Worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        logger.info("BaseApp stopped.")
