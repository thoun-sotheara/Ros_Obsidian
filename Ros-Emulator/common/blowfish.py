import struct
from pathlib import Path

_M = 0xFFFFFFFF

# Standard Blowfish initial P-box and S-boxes
_P_INIT = [
    0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344, 0xA4093822, 0x299F31D0,
    0x082EFA98, 0xEC4E6C89, 0x452821E6, 0x38D01377, 0xBE5466CF, 0x34E90C6C,
    0xC0AC29B7, 0xC97C50DD, 0x3F84D5B5, 0xB5470917, 0x9216D5D9, 0x8979FB1B
]

class BlowfishCtx:
    def __init__(self, ctx_bytes: bytes = None):
        if ctx_bytes:
            self.P = list(struct.unpack_from("<18I", ctx_bytes, 0))
            self.S = list(struct.unpack_from("<1024I", ctx_bytes, 0x48))
        else:
            self.P = list(_P_INIT)
            self.S = [0] * 1024

    @classmethod
    def from_file(cls, path: Path | str) -> "BlowfishCtx":
        with open(path, "rb") as f:
            return cls(f.read())

    def _f(self, x: int) -> int:
        S = self.S
        a = (x >> 24) & 0xFF
        b = (x >> 16) & 0xFF
        c = (x >> 8) & 0xFF
        d = x & 0xFF
        return ((((S[a] + S[0x100 + b]) & _M) ^ S[0x200 + c]) + S[0x300 + d]) & _M

    def _enc_block(self, L: int, R: int) -> tuple[int, int]:
        P = self.P
        for i in range(16):
            L ^= P[i]
            R ^= self._f(L)
            L, R = R, L
        L, R = R, L
        R ^= P[16]
        L ^= P[17]
        return L & _M, R & _M

    def _dec_block(self, L: int, R: int) -> tuple[int, int]:
        P = self.P
        for i in range(17, 1, -1):
            L ^= P[i]
            R ^= self._f(L)
            L, R = R, L
        L, R = R, L
        R ^= P[1]
        L ^= P[0]
        return L & _M, R & _M

    def encrypt_cbc_iv0(self, data: bytes) -> bytes:
        """BigWorld Plaintext-chaining CBC encryption, big-endian words."""
        assert len(data) % 8 == 0, f"Data length must be multiple of 8, got {len(data)}"
        out = bytearray()
        pL = pR = 0
        for i in range(0, len(data), 8):
            L, R = struct.unpack_from(">II", data, i)
            keepL, keepR = L, R
            L ^= pL
            R ^= pR
            cL, cR = self._enc_block(L, R)
            out += struct.pack(">II", cL, cR)
            pL, pR = keepL, keepR  # chains with previous PLAINTEXT block
        return bytes(out)

    def decrypt_cbc_iv0(self, data: bytes) -> bytes:
        """BigWorld Plaintext-chaining CBC decryption, big-endian words."""
        assert len(data) % 8 == 0, f"Data length must be multiple of 8, got {len(data)}"
        out = bytearray()
        pL = pR = 0
        for i in range(0, len(data), 8):
            cL, cR = struct.unpack_from(">II", data, i)
            pL_dec, pR_dec = self._dec_block(cL, cR)
            pL_dec ^= pL
            pR_dec ^= pR
            out += struct.pack(">II", pL_dec, pR_dec)
            pL, pR = pL_dec, pR_dec  # chains with recovered PLAINTEXT block
        return bytes(out)
