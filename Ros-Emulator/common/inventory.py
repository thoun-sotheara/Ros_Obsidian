import json
from pathlib import Path

from config.settings import BASE_DIR

CATALOG_PATH = BASE_DIR / "data" / "free_catalog.json"


def load_free_catalog() -> dict:
    with CATALOG_PATH.open("r", encoding="utf-8") as source:
        catalog = json.load(source)
    if catalog.get("version") != 1:
        raise RuntimeError("unsupported free inventory catalog version")
    if catalog.get("vip_level") != 0:
        raise RuntimeError("free catalog must keep vip_level at standard free status")
    return catalog


def _uuid(category: str, item_id: int) -> bytes:
    seed = f"free-{category}-{item_id}".encode("utf-8")
    import hashlib
    return hashlib.sha256(seed).digest()[:16]


def build_free_item_package() -> dict:
    """Build dtsItemPackage using the fixed 32-bit avatar schema types."""
    catalog = load_free_catalog()
    entries = []
    for category, items in catalog["items"].items():
        for item in items:
            entries.append({
                "uuid": _uuid(category, int(item["item_id"])),
                "itemID": int(item["item_id"]),
                "number": int(item.get("number", 1)),
                "info": {},
            })
    return {
        "itemList": entries,
        "layoutInfo": [],
        "_packageCapacity": len(entries),
    }


def build_free_appearance_packages() -> dict:
    """Build costume and vehicle package properties for the avatar stream."""
    catalog = load_free_catalog()
    result = {}
    for package_name, category in (("costumePackage", "costumes"), ("vehiclePackage", "vehicle_skins")):
        item_list = []
        for item in catalog["items"].get(category, []):
            item_list.append({
                "uuid": _uuid(category, int(item["item_id"])),
                "itemID": int(item["item_id"]),
                "number": int(item.get("number", 1)),
                "info": {},
            })
        result[package_name] = {
            "itemList": item_list,
            "layoutInfo": [],
            "_packageCapacity": len(item_list),
        }
    return result


def default_loadout() -> dict:
    catalog = load_free_catalog()
    return {
        "costume_item_id": catalog["defaults"]["costume_item_id"],
        "weapon_skin_item_id": catalog["defaults"]["weapon_skin_item_id"],
        "parachute_item_id": catalog["defaults"]["parachute_item_id"],
        "vehicle_skin_item_id": catalog["defaults"]["vehicle_skin_item_id"],
        "profile_frame_item_id": catalog["defaults"]["profile_frame_item_id"],
        "vip_level": 0,
        "premium": False,
    }


def merge_loadout(saved: dict | None) -> dict:
    result = default_loadout()
    if isinstance(saved, dict):
        for key in ("costume_item_id", "weapon_skin_item_id", "parachute_item_id", "vehicle_skin_item_id", "profile_frame_item_id"):
            if isinstance(saved.get(key), int):
                result[key] = saved[key]
    result["vip_level"] = 0
    result["premium"] = False
    return result
