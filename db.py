"""Firebase RTDB storage layer — all calls async-safe via asyncio.to_thread."""
import asyncio
import logging
import random
import string
import time
from typing import Any, Optional

import firebase_admin
from firebase_admin import credentials, db

import config

log = logging.getLogger("db")

_app_initialized = False


def init() -> None:
    global _app_initialized
    if _app_initialized:
        return
    if config.FIREBASE_SERVICE_ACCOUNT:
        cred = credentials.Certificate(config.FIREBASE_SERVICE_ACCOUNT)  # dict = service-account info
    else:
        cred = credentials.Certificate(config.FIREBASE_SA_PATH)
    firebase_admin.initialize_app(cred, {"databaseURL": config.FIREBASE_DB_URL})
    _app_initialized = True
    log.info("firebase connected: %s", config.FIREBASE_DB_URL)


def _r(path: str) -> db.Reference:
    return db.reference(f"{config.DB_ROOT}/{path}")


async def aget(path: str) -> Any:
    return await asyncio.to_thread(lambda: _r(path).get())


async def aset(path: str, value: Any) -> None:
    await asyncio.to_thread(lambda: _r(path).set(value))


async def aupdate(path: str, value: dict) -> None:
    await asyncio.to_thread(lambda: _r(path).update(value))


async def adelete(path: str) -> None:
    await asyncio.to_thread(lambda: _r(path).delete())


# ─── IDs ─────────────────────────────────────────────────────────────────────

ALPHABET = string.ascii_letters + string.digits


def new_id(n: int = 10) -> str:
    return "".join(random.SystemRandom().choices(ALPHABET, k=n))


async def unique_id(path: str, tries: int = 5) -> str:
    """Random id that does not collide inside `path`."""
    for _ in range(tries):
        fid = new_id()
        if not await aget(f"{path}/{fid}"):
            return fid
    return new_id(14)  # practically impossible to collide


# ─── Users ───────────────────────────────────────────────────────────────────

async def upsert_user(uid: int, name: str, username: Optional[str]) -> None:
    await aupdate(
        f"users/{uid}",
        {
            "name": (name or "")[:64],
            "username": (username or "").lstrip("@")[:32],
            "last_seen": int(time.time() * 1000),
        },
    )
    # keep joined_at if new
    u = await aget(f"users/{uid}")
    if not u or not u.get("joined_at"):
        await aset(f"users/{uid}/joined_at", int(time.time() * 1000))


async def get_user(uid: int) -> Optional[dict]:
    return await aget(f"users/{uid}")


async def set_banned(uid: int, banned: bool) -> None:
    await aset(f"users/{uid}/banned", banned)


async def all_users() -> dict:
    return await aget("users") or {}


async def inc_upload_count(uid: int) -> None:
    u = await aget(f"users/{uid}/uploads")
    await aset(f"users/{uid}/uploads", (u or 0) + 1)


# ─── Files ───────────────────────────────────────────────────────────────────

async def save_file(fid: str, data: dict) -> None:
    data = dict(data)
    data["created_at"] = int(time.time() * 1000)
    data["clicks"] = 0
    await aset(f"files/{fid}", data)


async def get_file(fid: str) -> Optional[dict]:
    return await aget(f"files/{fid}")


async def delete_file(fid: str) -> None:
    await adelete(f"files/{fid}")


async def add_click(fid: str) -> None:
    c = await aget(f"files/{fid}/clicks")
    await aset(f"files/{fid}/clicks", (c or 0) + 1)


async def all_files() -> dict:
    return await aget("files") or {}


# ─── Batches ─────────────────────────────────────────────────────────────────

async def save_batch(bid: str, fids: list[str], owner_id: int) -> None:
    await aset(
        f"batches/{bid}",
        {"ids": fids, "owner_id": owner_id, "created_at": int(time.time() * 1000)},
    )


async def get_batch(bid: str) -> Optional[dict]:
    return await aget(f"batches/{bid}")


async def all_batches() -> dict:
    return await aget("batches") or {}


# ─── Channels (force-sub) ────────────────────────────────────────────────────

async def get_channels() -> dict:
    return await aget("settings/channels") or {}


async def save_channel(chat_id: int, data: dict) -> None:
    await aset(f"settings/channels/{chat_id}", data)


async def delete_channel(chat_id: int) -> None:
    await adelete(f"settings/channels/{chat_id}")


# ─── Config ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "autosub_button": True,   # auto "Join channel" button on delivered files
    "protect": False,         # protect_content (no forward/save)
    "autodel_sec": config.AUTO_DELETE_SECONDS,
    "welcome": "",
    "notice_text": "",        # custom auto-delete notice; "" = default text, "OFF" = no notice msg
}


async def get_support_users() -> list[str]:
    return await aget("settings/support_users") or []


async def set_support_users(users: list[str]) -> None:
    await aset("settings/support_users", users)


async def get_config() -> dict:
    c = await aget("settings/config") or {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(c)
    return merged


async def update_config(patch: dict) -> None:
    await aupdate("settings/config", patch)


# ─── Pending (payload saved while user does force-sub) ──────────────────────

async def save_pending(uid: int, ptype: str, pid: str) -> None:
    await aset(f"pending/{uid}", {"type": ptype, "id": pid, "ts": int(time.time() * 1000)})


async def pop_pending(uid: int) -> Optional[dict]:
    p = await aget(f"pending/{uid}")
    if p:
        await adelete(f"pending/{uid}")
    return p


# ─── Admins (env + bootstrapped) ─────────────────────────────────────────────

async def bootstrap_admin(uid: int) -> None:
    ids = await aget("settings/admin_ids") or []
    if uid not in ids:
        ids.append(uid)
        await aset("settings/admin_ids", ids)


async def all_admin_ids() -> set[int]:
    ids = await aget("settings/admin_ids") or []
    return set(config.ADMIN_IDS) | {int(i) for i in ids}


async def remove_admin(uid: int) -> None:
    ids = await aget("settings/admin_ids") or []
    ids = [i for i in ids if int(i) != uid]
    await aset("settings/admin_ids", ids)
