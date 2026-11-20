"""User-side handlers: start (deep-link), force-sub verify, uploads, batch, info."""
import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import core
import db
import keyboards

log = logging.getLogger("user")
router = Router()


class BatchState(StatesGroup):
    collecting = State()


FILE_FILTER = F.document | F.video | F.audio | F.photo | F.voice | F.animation | F.sticker


# ─── helpers ─────────────────────────────────────────────────────────────────

def extract_file(m: Message) -> tuple[str, str, str | None, int | None]:
    """-> (ftype, file_id, file_name, file_size)"""
    if m.document:
        return ("document", m.document.file_id, m.document.file_name, m.document.file_size)
    if m.video:
        return ("video", m.video.file_id, m.video.file_name, m.video.file_size)
    if m.audio:
        return ("audio", m.audio.file_id, m.audio.file_name, m.audio.file_size)
    if m.photo:
        return ("photo", m.photo[-1].file_id, None, m.photo[-1].file_size)
    if m.voice:
        return ("voice", m.voice.file_id, "voice.ogg", m.voice.file_size)
    if m.animation:
        return ("animation", m.animation.file_id, m.animation.file_name, m.animation.file_size)
    if m.sticker:
        return ("sticker", m.sticker.file_id, None, None)
    return ("", "", None, None)


async def is_admin(uid: int) -> bool:
    return uid in await db.all_admin_ids()


def human_size(n: int | None) -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, bot: Bot, state: FSMContext):
    uid = m.from_user.id
    u = await db.get_user(uid)
    if u and u.get("banned"):
        return await m.answer("🚫 <b>You are banned from using this bot.</b>", parse_mode="HTML")
    await db.upsert_user(uid, m.from_user.full_name, m.from_user.username)
    await state.clear()

    payload = (command.args or "").strip()
    parsed = core.parse_payload(payload)

    if parsed:
        ptype, pid = parsed
        nj = await core.not_joined_channels(bot, uid)
        if nj:
            await db.save_pending(uid, ptype, pid)
            name = html.escape(m.from_user.first_name or "Friend")
            await m.answer(
                f"🔐 <b>Hello {name}!</b>\n\n"
                f"⚠️ <b>To get your file you must join our channel(s) first:</b>\n\n"
                f"1️⃣ Join all channel(s) below\n"
                f"2️⃣ Press <b>✅ Verify &amp; Get File</b>\n"
                f"3️⃣ Your file will be delivered instantly 📥",
                reply_markup=keyboards.force_sub_kb(nj),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        await core.deliver_payload(bot, uid, ptype, pid)
        return

    # plain start
    cfg = await db.get_config()
    url = core._updates_button_url(await db.get_channels())
    name = html.escape(m.from_user.full_name or "Friend")
    welcome = (cfg.get("welcome") or "").strip()
    text = (
        f"{welcome}\n\n" if welcome else
        f"👋 <b>Welcome, {name}!</b>\n\n"
        f"🤖 <b>{config.BOT_NAME} — File Store Bot</b>\n\n"
        f"📤 <b>Main kya kar sakta hu?</b>\n"
        f"• Owner kisi bhi file ko host karke share link bana sakta hai\n"
        f"• Link click karo → channel join karo → ✅ Verify → file milegi 📥\n"
        f"• Files auto-delete ho sakti hain — turant save kar lena\n"
    )
    await m.answer(text, reply_markup=keyboards.start_kb(url), parse_mode="HTML", disable_web_page_preview=True)


# ─── verify callback ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "verify")
async def cb_verify(c: CallbackQuery, bot: Bot):
    uid = c.from_user.id
    nj = await core.not_joined_channels(bot, uid)
    if nj:
        return await c.answer(
            "❌ Abhi bhi join nahi kiya! Pehle saare channel join karo, phir Verify dabao.",
            show_alert=True,
        )
    p = await db.pop_pending(uid)
    if not p:
        return await c.answer("⚠️ No pending file — please open the link again.", show_alert=True)
    try:
        await c.message.edit_reply_markup(reply_markup=keyboards.remove_kb())
    except Exception:
        pass
    await c.answer("✅ Verified! Sending your file...", show_alert=False)
    await core.deliver_payload(bot, uid, p["type"], p["id"])


@router.callback_query(F.data == "about")
async def cb_about(c: CallbackQuery):
    await c.answer()
    await c.message.answer(
        f"ℹ️ <b>{config.BOT_NAME}</b>\n"
        f"🛠 Owner: <b>{config.OWNER_NAME}</b>\n"
        f"🔗 File hosting + force-subscribe delivery bot\n"
        f"⚡ Powered by aiogram 3 + Firebase",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await c.answer()
    await c.message.answer(
        "🆘 <b>How to use</b>\n\n"
        "1️⃣ File link pe click karo\n"
        "2️⃣ Saare channels join karo 📢\n"
        "3️⃣ <b>✅ Verify &amp; Get File</b> dabao\n"
        "4️⃣ File aa jayegi 📥 (turant save karo — auto-delete ho sakti hai)\n\n"
        f"⚠️ Problem? Owner se contact karo: <b>{config.OWNER_NAME}</b>",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "🆘 <b>How to use</b>\n\n"
        "1️⃣ File link pe click karo\n"
        "2️⃣ Saare channels join karo 📢\n"
        "3️⃣ <b>✅ Verify &amp; Get File</b> dabao\n"
        "4️⃣ File aa jayegi 📥 (turant save karo — auto-delete ho sakti hai)\n\n"
        f"⚠️ Problem? Owner se contact karo: <b>{config.OWNER_NAME}</b>",
        parse_mode="HTML",
    )


@router.message(Command("about"))
async def cmd_about(m: Message):
    await m.answer(
        f"ℹ️ <b>{config.BOT_NAME}</b>\n"
        f"🛠 Owner: <b>{config.OWNER_NAME}</b>\n"
        f"🔗 File hosting + force-subscribe delivery bot\n"
        f"⚡ Powered by aiogram 3 + Firebase",
        parse_mode="HTML",
    )


@router.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"🆔 <b>Your ID:</b> <code>{m.from_user.id}</code>", parse_mode="HTML")


# ─── Batch flow (admin-only) ─────────────────────────────────────────────────

@router.message(Command("batch"))
async def cmd_batch(m: Message, state: FSMContext):
    uid = m.from_user.id
    if not await is_admin(uid):
        return await m.answer("🔒 Batch sirf admin ke liye hai.", parse_mode="HTML")
    await state.set_state(BatchState.collecting)
    await state.update_data(ids=[])
    await m.answer(
        "📦 <b>Batch Mode ON</b>\n\n"
        "Ab saari files bhejo (ek ek karke)...\n"
        "Jab sab bhej do → <b>/done</b> bhejo, ek single link milegi.\n"
        "Cancel karne ke liye: <b>/cancel</b>",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), StateFilter(BatchState.collecting))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❌ Batch cancelled.")


@router.message(Command("done"), StateFilter(BatchState.collecting))
async def cmd_done(m: Message, state: FSMContext):
    data = await state.get_data()
    ids = data.get("ids") or []
    if not ids:
        return await m.answer("⚠️ Batch khali hai — pehle files bhejo, ya /cancel karo.")
    bid = await db.unique_id("batches")
    await db.save_batch(bid, ids, m.from_user.id)
    await state.clear()
    await m.answer(
        f"✅ <b>Batch ready! {len(ids)} file(s)</b>\n\n"
        f"🔗 <b>Share this link:</b>\n<code>{core.batch_link(bid)}</code>\n\n"
        f"🔗 Link open karne pe user ko saare channels join karne honge, phir files milengi.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(StateFilter(BatchState.collecting), FILE_FILTER)
async def batch_collect(m: Message, state: FSMContext):
    data = await state.get_data()
    ids = data.get("ids") or []
    ftype, file_id, fname, fsize = extract_file(m)
    fid = await db.unique_id("files")
    await db.save_file(fid, {
        "file_id": file_id, "ftype": ftype, "caption": m.caption or "",
        "fname": fname, "fsize": fsize, "owner_id": m.from_user.id,
    })
    ids.append(fid)
    await state.update_data(ids=ids)
    await m.answer(f"✅ Added ({len(ids)} file(s)) — <code>{fid}</code>\nSab bhejne ke baad <b>/done</b> bhejo.", parse_mode="HTML")


# ─── Single file upload ──────────────────────────────────────────────────────

@router.message(FILE_FILTER)
async def on_file(m: Message):
    uid = m.from_user.id
    u = await db.get_user(uid)
    if u and u.get("banned"):
        return
    open_uploads = getattr(config, "OPEN_UPLOADS", False)
    if not open_uploads and not await is_admin(uid):
        return await m.answer(
            f"🔒 <b>File hosting admin-only hai.</b>\n"
            f"File link chahiye? Owner se contact karo: <b>{config.OWNER_NAME}</b>",
            parse_mode="HTML",
        )
    if core.rate_limited(uid):
        return await m.answer("🌶 <b>Too fast!</b> Thoda ruk kar try karo (10 files/min max).", parse_mode="HTML")

    ftype, file_id, fname, fsize = extract_file(m)
    if not ftype:
        return
    fid = await db.unique_id("files")
    await db.save_file(fid, {
        "file_id": file_id, "ftype": ftype, "caption": m.caption or "",
        "fname": fname, "fsize": fsize, "owner_id": uid,
    })
    await db.inc_upload_count(uid)
    await m.answer(
        f"✅ <b>File stored successfully!</b>\n\n"
        f"🗂 <b>Info:</b>\n"
        f"• Type: <b>{ftype}</b>\n"
        f"• Size: <b>{human_size(fsize)}</b>\n"
        f"• ID: <code>{fid}</code>\n\n"
        f"🔗 <b>Share this link:</b>\n<code>{core.file_link(fid)}</code>\n\n"
        f"💡 Ek link me multiple files chahiye? <b>/batch</b> use karo (admin).\n"
        f"⏱ {time.strftime('%d %b %Y, %I:%M %p')}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
