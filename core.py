"""Core logic: force-sub check, payload resolution, delivery, rate limiting."""
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message

import config
import db
import keyboards

log = logging.getLogger("core")

SEND_METHODS = {
    # ftype -> (bot method, file_id kwarg name)
    "document": ("send_document", "document"),
    "video": ("send_video", "video"),
    "audio": ("send_audio", "audio"),
    "photo": ("send_photo", "photo"),
    "voice": ("send_voice", "voice"),
    "animation": ("send_animation", "animation"),
    "sticker": ("send_sticker", "sticker"),
}

# ─── Rate limiter (uploads) ──────────────────────────────────────────────────

_uploads: dict[int, deque] = defaultdict(lambda: deque(maxlen=60))


def rate_limited(uid: int) -> bool:
    now = time.time()
    dq = _uploads[uid]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= config.UPLOAD_RATE_LIMIT:
        return True
    dq.append(now)
    return False


# ─── Bot username ────────────────────────────────────────────────────────────

_bot_username: str = config.BOT_USERNAME


async def resolve_username(bot: Bot) -> str:
    global _bot_username
    try:
        me = await bot.get_me()
        _bot_username = me.username
    except Exception as e:  # keep fallback
        log.warning("get_me failed (%s), using %s", e, _bot_username)
    return _bot_username


def file_link(fid: str) -> str:
    return keyboards.t_me_link(_bot_username, f"file_{fid}")


def batch_link(bid: str) -> str:
    return keyboards.t_me_link(_bot_username, f"batch_{bid}")


# ─── Updates channel (for auto-sub button) ───────────────────────────────────


def _updates_button_url(channels: dict) -> Optional[str]:
    """URL for the auto-sub button: UPDATES_CHANNEL env first, else first channel."""
    if config.UPDATES_CHANNEL:
        return f"https://t.me/{config.UPDATES_CHANNEL}"
    for ch in channels.values():
        if ch.get("username"):
            return f"https://t.me/{ch['username']}"
    for ch in channels.values():
        if ch.get("invite_link"):
            return ch["invite_link"]
    return None


# ─── Force-sub membership check ──────────────────────────────────────────────

_OK_STATUS = {"creator", "administrator", "member"}


async def not_joined_channels(bot: Bot, uid: int) -> list[dict]:
    """Channels the user has NOT joined. [{chat_id, title, url}]"""
    channels = await db.get_channels()
    not_joined: list[dict] = []
    for chat_id, ch in channels.items():
        try:
            m = await bot.get_chat_member(int(chat_id), uid)
            status = getattr(m, "status", "")
            is_member = status in _OK_STATUS or (status == "restricted" and getattr(m, "is_member", False))
            if not is_member:
                not_joined.append(_channel_btn(int(chat_id), ch))
        except Exception as e:
            log.warning("get_chat_member %s failed: %s — treating as joined (bot may have lost admin)", chat_id, e)
            # don't lock users out if the bot lost admin in one channel
    return not_joined


def _channel_btn(chat_id: int, ch: dict) -> dict:
    url = f"https://t.me/{ch['username']}" if ch.get("username") else ch.get("invite_link") or f"https://t.me/{chat_id}"
    return {"chat_id": chat_id, "title": ch.get("title") or "Channel", "url": url}


async def refresh_invite_link(bot: Bot, chat_id: int, ch: dict) -> Optional[str]:
    """(Re)create invite link for a private channel; returns new url or None."""
    if ch.get("username"):
        return f"https://t.me/{ch['username']}"
    try:
        inv = await bot.create_chat_invite_link(chat_id=int(chat_id))
        url = inv.invite_link
        ch["invite_link"] = url
        await db.save_channel(chat_id, ch)
        return url
    except Exception as e:
        log.warning("create_chat_invite_link %s failed: %s", chat_id, e)
        return None


# ─── Payload resolution ──────────────────────────────────────────────────────

def parse_payload(payload: str) -> Optional[tuple[str, str]]:
    if payload.startswith("file_"):
        pid = payload[5:]
        return ("file", pid) if pid else None
    if payload.startswith("batch_"):
        pid = payload[6:]
        return ("batch", pid) if pid else None
    return None


# ─── Delivery ────────────────────────────────────────────────────────────────

async def _send_one(bot: Bot, chat_id: int, f: dict, protect: bool, kb: Optional[InlineKeyboardMarkup]) -> Optional[Message]:
    spec = SEND_METHODS.get(f.get("ftype", ""))
    if not spec:
        return None
    method, kwarg = spec
    args: dict = {"chat_id": chat_id, "protect_content": protect}
    if kb and kb.inline_keyboard:
        args["reply_markup"] = kb
    if method != "send_sticker":
        args["caption"] = f.get("caption") or ""
    try:
        return await getattr(bot, method)(**{kwarg: f["file_id"]}, **args)
    except Exception as e:
        log.error("send %s failed: %s", f.get("ftype"), e)
        return None


# ─── Auto-delete notice (custom text via /setnotice) ─────────────────────────

def human_dur(secs: int) -> str:
    if secs >= 3600 and secs % 3600 == 0:
        return f"{secs // 3600} hour(s)"
    if secs >= 60:
        return f"{max(1, secs // 60)} minute(s)"
    return f"{secs} second(s)"


def _notice_text(cfg: dict, sent: int, is_batch: bool) -> str:
    """Custom admin text wins ({time}/{count} placeholders); 'OFF' = no notice; else default."""
    dur = human_dur(int(cfg.get("autodel_sec") or 0))
    custom = (cfg.get("notice_text") or "").strip()
    if custom:
        if custom.upper() == "OFF":
            return ""
        return custom.replace("{time}", dur).replace("{count}", str(sent))
    if is_batch:
        return (
            f"⚠️ <b>Auto-Delete Enabled!</b>\n\n"
            f"🛡 All {sent} file(s) will be <b>auto-deleted in {dur}</b>.\n"
            f"📥 Save / forward them now if you need them later."
        )
    return (
        f"⚠️ <b>Auto-Delete Enabled!</b>\n\n"
        f"🛡 This file will be <b>auto-deleted in {dur}</b>.\n"
        f"📥 Save / forward it now if you need it later."
    )


async def schedule_autodelete(bot: Bot, chat_id: int, msg_ids: list[int], seconds: int, notice_id: Optional[int]) -> None:
    async def _job():
        await asyncio.sleep(seconds)
        for mid in ([notice_id] if notice_id else []) + msg_ids:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                pass
    asyncio.create_task(_job())


async def deliver_file(bot: Bot, uid: int, f: dict) -> bool:
    cfg = await db.get_config()
    kb = None
    if cfg["autosub_button"]:
        url = _updates_button_url(await db.get_channels())
        if url:
            kb = keyboards.file_kb(url)
    msg = await _send_one(bot, uid, f, bool(cfg["protect"]), kb)
    if not msg:
        return False
    fid = f.get("_id")
    if fid:
        await db.add_click(str(fid))

    notice_id = None
    secs = int(cfg.get("autodel_sec") or 0)
    if secs > 0:
        text = _notice_text(cfg, sent=1, is_batch=False)
        if text:
            warn = await bot.send_message(uid, text, parse_mode="HTML")
            notice_id = warn.message_id
        await schedule_autodelete(bot, uid, [msg.message_id], secs, notice_id)
    return True


async def deliver_batch(bot: Bot, uid: int, ids: list[str]) -> int:
    cfg = await db.get_config()
    kb = None
    if cfg["autosub_button"]:
        url = _updates_button_url(await db.get_channels())
        if url:
            kb = keyboards.file_kb(url)
    protect = bool(cfg["protect"])
    sent = 0
    sent_msgs: list[int] = []
    for fid in ids:
        f = await db.get_file(fid)
        if not f:
            continue
        f["_id"] = fid
        msg = await _send_one(bot, uid, f, protect, kb)
        if msg:
            sent += 1
            sent_msgs.append(msg.message_id)
            await db.add_click(fid)
        await asyncio.sleep(0.35)  # flood-safe
    secs = int(cfg.get("autodel_sec") or 0)
    if secs > 0 and sent_msgs:
        text = _notice_text(cfg, sent=sent, is_batch=True)
        if text:
            warn = await bot.send_message(uid, text, parse_mode="HTML")
            await schedule_autodelete(bot, uid, sent_msgs, secs, warn.message_id)
        else:
            await schedule_autodelete(bot, uid, sent_msgs, secs, None)
    return sent


async def deliver_payload(bot: Bot, uid: int, ptype: str, pid: str) -> bool:
    """Returns True if delivered (or payload invalid → False after notifying)."""
    if ptype == "file":
        f = await db.get_file(pid)
        if not f:
            await bot.send_message(uid, "⚠️ <b>Invalid or expired file link!</b>\n🔗 Ask the sender for a fresh link.", parse_mode="HTML")
            return False
        f["_id"] = pid
        return await deliver_file(bot, uid, f)
    b = await db.get_batch(pid)
    if not b:
        await bot.send_message(uid, "⚠️ <b>Invalid or expired batch link!</b>", parse_mode="HTML")
        return False
    sent = await deliver_batch(bot, uid, b.get("ids") or [])
    if sent == 0:
        await bot.send_message(uid, "⚠️ <b>Batch files are no longer available.</b>", parse_mode="HTML")
        return False
    return True
