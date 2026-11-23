"""Schema-driven OLD 32-bit Avatar BASE_AND_CLIENT stream encoder."""

import hashlib
import json
import os
import pickle
import struct
from pathlib import Path
from config.settings import AVATAR_SCHEMA_PATH
from common.inventory import (
    build_free_item_package,
    build_free_appearance_packages,
    merge_loadout,
)

EXPECTED_EXE_SHA256 = (
    "184962db92cecdbf1afb78c97d2f7d8c3b6959c7b6bffe2e782795ae1fe81d89"
)
EXPECTED_ORDER_SHA256 = (
    "6d2f690f86d225c018cf877faec5510047636e954a46f0b0fc47ebc8086f3282"
)
EXPECTED_DEFAULT_STREAM_SHA256 = (
    "91cb5f44754750056f498ae1d8e3f403fbf52a5e9ac50c04589cfd06e3879172"
)


def _packed_length(length: int) -> bytes:
    if length < 0 or length > 0xFFFFFF:
        raise ValueError(f"OLD packed length outside 24-bit range: {length}")
    if length < 0xFF:
        return struct.pack("<B", length)
    return b"\xff" + struct.pack("<I", length)[:3]


def _decode_json_value(value):
    if isinstance(value, dict):
        if set(value) == {"bytes_hex"}:
            return bytes.fromhex(value["bytes_hex"])
        return {key: _decode_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_json_value(item) for item in value]
    return value


def _text_bytes(value, label: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError(f"{label} requires text/bytes")


def _pickle2(value, label: str) -> bytes:
    if value not in ({}, []):
        raise ValueError(f"{label} has no confirmed Python-2 portable value")
    data = pickle.dumps(value, protocol=2)
    expected = b"\x80\x02}q\x00." if value == {} else b"\x80\x02]q\x00."
    if data != expected:
        raise RuntimeError(f"host protocol-2 encoding differs for {label}")
    return data


def encode_value(type_spec: dict, value, label: str) -> bytes:
    kind = type_spec["kind"]
    formats = {
        "int8": "<b", "int16": "<h", "uint16": "<H",
        "int32": "<i", "uint32": "<I", "int64": "<q",
        "uint64": "<Q", "float32": "<f",
    }
    if kind in formats:
        return struct.pack(formats[kind], value)
    if kind in ("blob", "string"):
        data = _text_bytes(value, label)
        return _packed_length(len(data)) + data
    if kind == "python":
        data = _pickle2(value, label)
        return _packed_length(len(data)) + data
    if kind == "array":
        values = list(value)
        fixed_size = int(type_spec["fixed_size"])
        if fixed_size and len(values) != fixed_size:
            raise ValueError(f"{label} requires exactly {fixed_size} elements")
        prefix = b"" if fixed_size else struct.pack("<I", len(values))
        return prefix + b"".join(
            encode_value(type_spec["element"], item, f"{label}[{index}]")
            for index, item in enumerate(values)
        )
    if kind == "fixed_dict":
        if type_spec.get("allow_none") or not isinstance(value, dict):
            raise ValueError(f"{label} requires a non-null fixed dictionary")
        field_names = [field["name"] for field in type_spec["fields"]]
        if set(value) != set(field_names):
            raise ValueError(f"{label} fixed-dict fields differ from OLD schema")
        return b"".join(
            encode_value(field["type"], value[field["name"]], f"{label}.{field['name']}")
            for field in type_spec["fields"]
        )
    raise NotImplementedError(f"unsupported OLD type kind {kind!r}")


def load_schema() -> dict:
    with open(AVATAR_SCHEMA_PATH, "r", encoding="utf-8") as source:
        schema = json.load(source)
    if schema.get("kind") != "old-avatar-base-schema":
        raise RuntimeError("OLD Avatar schema kind mismatch")
    if schema.get("format_version") != 1:
        raise RuntimeError("OLD Avatar schema version mismatch")
    if schema.get("old_exe_sha256") != EXPECTED_EXE_SHA256:
        raise RuntimeError("OLD Avatar executable provenance mismatch")
    if schema.get("property_order_sha256") != EXPECTED_ORDER_SHA256:
        raise RuntimeError("OLD Avatar property-order hash mismatch")
    roots = schema.get("roots") or []
    if len(roots) != 94:
        raise RuntimeError("OLD Avatar schema must contain 94 roots")
    for index, root in enumerate(roots):
        if root.get("base_ordinal") != index:
            raise RuntimeError("OLD Avatar root order is not contiguous")
    return schema


def _server_values(schema: dict, loadout: dict | None = None) -> dict:
    values = {root["name"]: _decode_json_value(root["default"]) for root in schema["roots"]}
    player_name = os.environ.get("ROS_PLAYER_NAME", "Survivor")
    equipped = merge_loadout(loadout)
    appearance_packages = build_free_appearance_packages()
    values.update({
        "dtsItemPackage": build_free_item_package(),
        "costumePackage": appearance_packages["costumePackage"],
        "vehiclePackage": appearance_packages["vehiclePackage"],
        "vehicleItemID": int(equipped["vehicle_skin_item_id"]),
        "holdingWeapon": str(equipped["weapon_skin_item_id"]).encode("utf-8"),
        "weaponBag": [
            str(equipped["weapon_skin_item_id"]).encode("utf-8"),
            str(equipped["parachute_item_id"]).encode("utf-8"),
        ],
        "playerName": player_name,
        "bindedPlayerName": player_name,
        "identifierName": player_name,
        "baseNickname": os.environ.get("ROS_PLAYER_NICK", "Survivor"),
        "gid": int(os.environ.get("ROS_PLAYER_GID", "10001"), 0),
        "currentMapID": int(os.environ.get("ROS_AVATAR_CURRENT_MAP_ID", "-1"), 0),
        "baseCharacterType": int(os.environ.get("ROS_BASE_CHARACTER_TYPE", "10002"), 0),
        "dtsAppearanceGender": int(os.environ.get("ROS_DTS_APPEARANCE_GENDER", "2"), 0),
    })
    uuid_hex = os.environ.get("ROS_PLAYER_UUID_HEX")
    if uuid_hex is not None:
        values["playerUUID"] = bytes.fromhex(uuid_hex)
    return values


def build_avatar_base_stream(with_rows: bool = False, loadout: dict | None = None):
    schema = load_schema()
    values = _server_values(schema, loadout=loadout)
    chunks = []
    rows = []
    offset = 0
    for root in schema["roots"]:
        name = root["name"]
        encoded = encode_value(root["type"], values[name], name)
        chunks.append(encoded)
        rows.append({
            "base_ordinal": root["base_ordinal"],
            "ordinal": root["ordinal"],
            "name": name,
            "offset": offset,
            "length": len(encoded)
        })
        offset += len(encoded)
    stream = b"".join(chunks)
    return (stream, rows) if with_rows else stream
