import struct

# Mercury Packet Flags
FLAG_HAS_REQUESTS         = 0x0001
FLAG_HAS_ACKS             = 0x0002
FLAG_ON_CHANNEL           = 0x0004
FLAG_IS_RELIABLE          = 0x0008
FLAG_IS_FRAGMENT          = 0x0010
FLAG_HAS_SEQUENCE_NUMBER  = 0x0020
FLAG_INDEXED_CHANNEL      = 0x0040
FLAG_HAS_CUMULATIVE_ACK   = 0x0080

# BigWorld Message Types / Commands
MSG_LOGIN_REPLY           = 0xFF  # BigWorld Mercury Reply
MSG_BASEAPP_LOGIN         = 0x00
MSG_AUTHENTICATE          = 0x01
MSG_BASEAPP_CREATE_CELL   = 0x02

def pack_mercury_reply(reply_id: int, payload: bytes) -> bytes:
    """
    Wrap payload in a BigWorld Mercury reply frame:
    Format: 00 00 ff <u32 length> <reply_id u32> <payload>
    """
    frame_len = len(payload) + 4  # length includes reply_id
    header = struct.pack("<BBBI", 0x00, 0x00, MSG_LOGIN_REPLY, frame_len)
    reply_hdr = struct.pack("<I", reply_id)
    return header + reply_hdr + payload

def parse_mercury_packet(data: bytes) -> dict:
    """
    Parse generic Mercury packet header.
    """
    if len(data) < 2:
        return {"error": "packet too short", "raw": data}

    flags = struct.unpack_from("<H", data, 0)[0]
    offset = 2

    res = {
        "flags": flags,
        "has_requests": bool(flags & FLAG_HAS_REQUESTS),
        "has_acks": bool(flags & FLAG_HAS_ACKS),
        "on_channel": bool(flags & FLAG_ON_CHANNEL),
        "is_reliable": bool(flags & FLAG_IS_RELIABLE),
        "is_fragment": bool(flags & FLAG_IS_FRAGMENT),
        "has_seq": bool(flags & FLAG_HAS_SEQUENCE_NUMBER),
        "raw_len": len(data),
    }

    if res["has_seq"] and len(data) >= offset + 4:
        res["seq"] = struct.unpack_from("<I", data, offset)[0]
        offset += 4

    res["body"] = data[offset:]
    return res
