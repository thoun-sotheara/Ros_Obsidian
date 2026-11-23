import os
import socket
import struct
import threading
import time
from pathlib import Path
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, Blowfish

from config.settings import (
    BIND_HOST, PUBLIC_HOST, LOGINAPP_PORT, BASEAPP_PORT,
    LOGINAPP_PRIV_KEY, BFCTX_PATH
)
from common.logger import ServerLogger
from common.blowfish import BlowfishCtx
from common.session_manager import SESSION_MANAGER
import account_manager

logger = ServerLogger("LOGINAPP")

class LoginAppServer:
    def __init__(self, host: str = BIND_HOST, port: int = LOGINAPP_PORT,
                 baseapp_port: int = BASEAPP_PORT, public_host: str = PUBLIC_HOST):
        self.host = host
        self.port = port
        self.baseapp_port = baseapp_port
        self.public_host = public_host
        self.running = False
        self.sock = None
        self.thread = None

        # Load RSA private key
        if not LOGINAPP_PRIV_KEY.exists():
            raise FileNotFoundError(f"RSA Private key not found: {LOGINAPP_PRIV_KEY}")
        with open(LOGINAPP_PRIV_KEY, "rb") as f:
            self.rsa_priv = RSA.import_key(f.read())
        self.rsa_cipher = PKCS1_OAEP.new(self.rsa_priv)

        # Load precomputed Blowfish context if available
        self.bfctx = BlowfishCtx.from_file(BFCTX_PATH) if BFCTX_PATH.exists() else None


    def _decrypt_login(self, data: bytes) -> tuple[bytes | None, int | None]:
        """Attempt RSA-OAEP decryption across possible packet offsets."""
        for off in (15, 16, 14, 13, 17):
            if off + 128 > len(data):
                continue
            try:
                pt = self.rsa_cipher.decrypt(data[off:off+128])
                if pt:
                    return pt, off
            except Exception:
                continue
        return None, None

    @staticmethod
    def _read_packed_string(data: bytes, offset: int) -> tuple[bytes, int]:
        n = data[offset]
        offset += 1
        if n == 0xFF:
            n = int.from_bytes(data[offset:offset+3], "little")
            offset += 3
        return data[offset:offset+n], offset + n

    def _parse_params(self, pt: bytes):
        """
        LogOnParams layout:
        flags(u8) | username(packed) | password(packed) | bf_session_key(packed) | digest(16) | tail(u32)
        """
        offset = 0
        flags = pt[offset]
        offset += 1
        user, offset = self._read_packed_string(pt, offset)
        token, offset = self._read_packed_string(pt, offset)
        bf_key, offset = self._read_packed_string(pt, offset)
        rest = pt[offset:]
        return flags, user, token, rest, bf_key

    def _bf_cbc_iv0_encrypt(self, key: bytes, data: bytes) -> bytes:
        """BigWorld plaintext-chaining Blowfish CBC (IV=0)."""
        ecb = Blowfish.new(key, Blowfish.MODE_ECB)
        out = bytearray()
        prev = b"\x00" * 8
        for i in range(0, len(data), 8):
            blk = data[i:i + 8]
            out += ecb.encrypt(bytes(a ^ b for a, b in zip(blk, prev)))
            prev = blk
        return bytes(out)

    def _build_reply_payload(self, bf_key: bytes) -> bytes:
        """
        BigWorld LoginReplyRecord:
        Status: 0x01 (LOGGED_ON)
        Record: baseAppAddr (4B IP + 2B port + 2B pad) + 8B zeros + sessionKey (u32)
        Magic: 0x32ef9816
        """
        status = b"\x01"
        baseapp_ip = socket.inet_aton(self.public_host)
        baseapp_port_bytes = struct.pack(">H", self.baseapp_port)
        session_key_u32 = struct.pack("<I", 0x12345678)

        record = (baseapp_ip + baseapp_port_bytes + b"\x00\x00" + (b"\x00" * 8) + session_key_u32)
        magic = struct.pack("<I", 0x32EF9816)
        varstr = b"\x00"
        plain = record + magic + varstr
        # Pad to 8-byte multiple
        if len(plain) % 8 != 0:
            plain += b"\x00" * (8 - (len(plain) % 8))

        # Encrypt with client's per-session key or fallback to bfctx
        if bf_key and 4 <= len(bf_key) <= 56:
            enc = self._bf_cbc_iv0_encrypt(bf_key, plain)
        elif self.bfctx:
            enc = self.bfctx.encrypt_cbc_iv0(plain)
        else:
            enc = plain

        return status + enc

    def _build_error_reply(self, bf_key: bytes, message: str) -> bytes:
        """Build a login failure response using the same channel encryption."""
        msg = message.encode("utf-8")
        packed_msg = struct.pack("<B", len(msg)) + msg
        plain = packed_msg
        if len(plain) % 8:
            plain += b"\x00" * (8 - (len(plain) % 8))

        if bf_key and 4 <= len(bf_key) <= 56:
            enc = self._bf_cbc_iv0_encrypt(bf_key, plain)
        elif self.bfctx:
            enc = self.bfctx.encrypt_cbc_iv0(plain)
        else:
            enc = plain
        return b"\x02" + enc

    def _frame_reply(self, reply_id: int, payload: bytes) -> bytes:
        """Outer Mercury reply frame: 00 00 ff <u32 len> <reply_id> <payload>"""
        msgbody = struct.pack("<I", reply_id) + payload
        lenval = len(msgbody)
        hdr = struct.pack("<H", 0x0000) + b"\xff" + struct.pack("<I", lenval)
        return hdr + msgbody

    def handle_packet(self, data: bytes, addr: tuple[str, int]):
        if len(data) < 130:
            return

        pt, off = self._decrypt_login(data)
        if pt is None:
            logger.warn(f"Packet ({len(data)} bytes) from {addr} could not be decrypted via RSA.")
            return

        flags, user, token, rest, bf_key = self._parse_params(pt)
        reply_id = struct.unpack_from("<I", data, 5)[0] if len(data) >= 9 else 0

        username = user.decode("utf-8", errors="replace")
        password = token.decode("utf-8", errors="replace")

        if not 4 <= len(bf_key) <= 56:
            logger.warn(f"Rejected login from {addr}: invalid Blowfish key length ({len(bf_key)}B)")
            return

        account = account_manager.verify_credentials(username, password)
        if account is None:
            existing = account_manager.get_account(username)
            if existing is None:
                account, message = account_manager.register(username, password)
                if account is None:
                    logger.warn(f"Rejected login from {addr}: {message}")
                    reply_pkt = self._frame_reply(reply_id, self._build_error_reply(bf_key if 4 <= len(bf_key) <= 56 else b"", message))
                    self.sock.sendto(reply_pkt, addr)
                    return
            else:
                message = "Incorrect password"
                logger.warn(f"Rejected login from {addr}: wrong password for {username!r}")
                reply_pkt = self._frame_reply(reply_id, self._build_error_reply(bf_key if 4 <= len(bf_key) <= 56 else b"", message))
                self.sock.sendto(reply_pkt, addr)
                return

        session = SESSION_MANAGER.register(
            username=username,
            role_id=account["role_id"],
            client_addr=addr,
            blowfish_key=bf_key,
            reply_id=reply_id,
        )

        logger.info(f"Accepted login from {addr}: user={user.decode(errors='replace')!r}, reply_id={reply_id}")
        logger.debug(f"Registered isolated session for role_id={session.role_id}")

        payload = self._build_reply_payload(bf_key)
        reply_pkt = self._frame_reply(reply_id, payload)

        self.sock.sendto(reply_pkt, addr)
        logger.info(f"Sent LOGGED_ON reply ({len(reply_pkt)} bytes) to {addr} -> BaseApp {self.public_host}:{self.baseapp_port}")

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.running = True
        logger.info(f"Listening on UDP {self.host}:{self.port} (Redirects to BaseApp :{self.baseapp_port})")

        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data:
                    continue
                self.handle_packet(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Receive loop error: {e}")
                    time.sleep(0.1)

    def start(self):
        if self.running:
            return
        self.thread = threading.Thread(target=self.run, name="LoginApp-Worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        logger.info("LoginApp stopped.")
