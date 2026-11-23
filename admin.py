"""Admin handlers: bootstrap, channels, broadcast, stats, bans, settings."""
import asyncio
import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

import config
import core
import db
import keyboards

log = logging.getLogger("admin")
router = Router()

START_TIME = time.time()


async def is_admin(uid: int) -> bool:
    return uid in await db.all_admin_ids()


async def deny(m: Message):
    await m.answer("⛔ <b>Admins only.</b>", parse_mode="HTML")


# ─── Bootstrap ───────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(m: Message, command: CommandObject):
    uid = m.from_user.id
    if await is_admin(uid):
        return await m.answer("✅ You are already an admin.")
    secret = (command.args or "").strip()
    if not secret:
        return await m.answer("Usage: <code>/admin &lt;secret&gt;</code>", parse_mode="HTML")
    if secret != config.ADMIN_SECRET:
        return await m.answer("❌ Wrong secret.")
    await db.bootstrap_admin(uid)
    await m.answer(
        f"✅ <b>Admin bootstrapped!</b>\n"
        f"🆔 <code>{uid}</code> ab admin hai.\n\n"
        f"Ab use karo: /addchannel /channels /batch /stats /broadcast ...",
        parse_mode="HTML",
    )


# ─── Channels ────────────────────────────────────────────────────────────────

def _parse_chat_target(arg: str, m: Message) -> tuple[str | int | None, str]:
    arg = (arg or "").strip()
    if arg:
        return arg, arg
    # reply to a forwarded channel post?
    rm = m.reply_to_message
    origin = getattr(rm, "forward_origin", None) if rm else None
    chat = getattr(origin, "chat", None) if origin else None
    if chat is not None:
        return chat.id, getattr(chat, "title", "") or str(chat.id)
    return None, ""


@router.message(Command("addchannel"))
async def cmd_addchannel(m: Message, command: CommandObject, bot: Bot):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    target, _ = _parse_chat_target(command.args, m)
    if target is None:
        return await m.answer(
            "Usage:\n<code>/addchannel @channelusername</code>\n<code>/addchannel -1001234567890</code>\n"
            "ya kisi channel post ko <b>forward karke reply</b> karo.",
            parse_mode="HTML",
        )
    try:
        chat = await bot.get_chat(target)
    except Exception as e:
        return await m.answer(f"❌ Chat nahi mila: <code>{html.escape(str(e))}</code>\nBot ko channel me add karo.", parse_mode="HTML")
    if chat.type not in ("channel", "supergroup"):
        return await m.answer("❌ Sirf channel ya supergroup allowed hai.", parse_mode="HTML")
    try:
        me_member = await bot.get_chat_member(chat.id, bot.id)
        if getattr(me_member, "status", "") not in ("administrator", "creator"):
            raise Exception("Bot is not admin there")
    except Exception:
        return await m.answer(
            f"⚠️ Pehle bot ko <b>{html.escape(chat.title or '')}</b> me <b>admin</b> banao "
            f"(invite users permission ke saath), phir dobara <code>/addchannel</code> karo.",
            parse_mode="HTML",
        )
    username = getattr(chat, "username", None)
    invite_link = None
    if not username:
        try:
            inv = await bot.create_chat_invite_link(chat.id)
            invite_link = inv.invite_link
        except Exception as e:
            return await m.answer(f"❌ Invite link nahi bana: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    await db.save_channel(chat.id, {
        "title": chat.title or str(chat.id),
        "username": username or "",
        "invite_link": invite_link or "",
        "added_by": m.from_user.id,
        "added_at": int(time.time() * 1000),
    })
    url = f"https://t.me/{username}" if username else invite_link
    test_kb = None
    if url:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        test_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Test Join", url=url)]])
    await m.answer(
        f"✅ <b>Channel added!</b>\n"
        f"• Title: <b>{html.escape(chat.title or str(chat.id))}</b>\n"
        f"• ID: <code>{chat.id}</code>\n\n"
        f"Ab har file link pe user ko pehle is channel ko join karna hoga 🔐",
        parse_mode="HTML",
        reply_markup=test_kb,
        disable_web_page_preview=True,
    )


@router.message(Command("channels"))
async def cmd_channels(m: Message, bot: Bot):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    channels = await db.get_channels()
    if not channels:
        return await m.answer("📭 Koi channel configured nahi hai. <code>/addchannel @name</code>", parse_mode="HTML")
    lines = ["📢 <b>Force-sub channels:</b>\n"]
    for i, (cid, ch) in enumerate(channels.items(), 1):
        ok = "✅"
        try:
            mem = await bot.get_chat_member(int(cid), bot.id)
            ok = "✅" if getattr(mem, "status", "") in ("administrator", "creator") else "⚠️ not admin"
        except Exception:
            ok = "⚠️ unreachable"
        lines.append(f"{i}. <b>{html.escape(ch.get('title',''))}</b> — <code>{cid}</code> {ok}")
    await m.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("delchannel"))
async def cmd_delchannel(m: Message, command: CommandObject, bot: Bot):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    arg = (command.args or "").strip()
    channels = await db.get_channels()
    if not channels:
        return await m.answer("📭 Koi channel nahi hai.")
    target_id: int | None = None
    if arg.lstrip("-").isdigit():
        target_id = int(arg)
    elif arg.startswith("@"):
        uname = arg[1:].lower()
        for cid, ch in channels.items():
            if (ch.get("username") or "").lower() == uname:
                target_id = int(cid)
                break
    elif arg.isdigit():  # index from /channels list
        idx = int(arg)
        keys = list(channels.keys())
        if 1 <= idx <= len(keys):
            target_id = int(keys[idx - 1])
    if target_id is None or str(target_id) not in channels:
        return await m.answer("❌ Channel nahi mila. List dekho: /channels", parse_mode="HTML")
    await db.delete_channel(target_id)
    await m.answer(f"✅ Channel <code>{target_id}</code> removed — force-sub band.", parse_mode="HTML")


# ─── Settings ────────────────────────────────────────────────────────────────

@router.message(Command("autosub"))
async def cmd_autosub(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    val = (command.args or "").strip().lower()
    if val not in ("on", "off"):
        cur = (await db.get_config())["autosub_button"]
        return await m.answer(f"Auto-sub button abhi: <b>{'ON' if cur else 'OFF'}</b>\nUsage: <code>/autosub on|off</code>", parse_mode="HTML")
    await db.update_config({"autosub_button": val == "on"})
    await m.answer(
        f"✅ Auto <b>📢 Join Channel</b> button on files: <b>{'ON (visible)' if val == 'on' else 'OFF (hidden)'}</b>",
        parse_mode="HTML",
    )


@router.message(Command("protect"))
async def cmd_protect(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    val = (command.args or "").strip().lower()
    if val not in ("on", "off"):
        cur = (await db.get_config())["protect"]
        return await m.answer(f"Protect content abhi: <b>{'ON' if cur else 'OFF'}</b>\nUsage: <code>/protect on|off</code>", parse_mode="HTML")
    await db.update_config({"protect": val == "on"})
    await m.answer(
        f"✅ Protect content: <b>{'ON — forward/save blocked' if val == 'on' else 'OFF'}</b>",
        parse_mode="HTML",
    )


@router.message(Command("autodel"))
async def cmd_autodel(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    arg = (command.args or "").strip().lstrip("-")
    if not arg.isdigit():
        cur = (await db.get_config())["autodel_sec"]
        return await m.answer(
            f"Auto-delete abhi: <b>{cur}s</b>\nUsage: <code>/autodel 600</code> (seconds, 0 = off)",
            parse_mode="HTML",
        )
    secs = int(arg)
    await db.update_config({"autodel_sec": secs})
    if secs == 0:
        await m.answer("✅ Auto-delete <b>OFF</b> — files kabhi delete nahi hongi.", parse_mode="HTML")
    else:
        await m.answer(f"✅ Files ab <b>{secs}s ({max(1, secs // 60)} min)</b> baad auto-delete hongi.", parse_mode="HTML")


@router.message(Command("welcome"))
async def cmd_welcome(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    text = (command.args or "").strip()
    if not text:
        return await m.answer("Usage: <code>/welcome Your text...</code> (HTML allowed) ya <code>/welcome off</code>", parse_mode="HTML")
    if text.lower() == "off":
        await db.update_config({"welcome": ""})
        return await m.answer("✅ Custom welcome hataya — default wapas.")
    await db.update_config({"welcome": text[:1024]})
    await m.answer("✅ Welcome text set!")


@router.message(Command("setnotice"))
async def cmd_setnotice(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    text = (command.args or "").strip()
    cur = (await db.get_config()).get("notice_text", "")
    if not text:
        state = "🔕 OFF (notice band)" if cur.upper() == "OFF" else (f"custom:\n\n{html.escape(cur)}" if cur else "default text")
        return await m.answer(
            "⚠️ <b>Auto-delete notice text</b>\n\n"
            f"Abhi: <b>{state}</b>\n\n"
            "Usage:\n"
            "<code>/setnotice ⚠️ File {time} me delete ho jayegi. Jaldi save karo!</code>\n"
            "<code>/setnotice default</code> — default text wapas\n"
            "<code>/setnotice off</code> — notice message band (file silently delete hogi)\n\n"
            "Placeholders: <code>{time}</code> = delete time, <code>{count}</code> = files. HTML allowed.",
            parse_mode="HTML",
        )
    if text.lower() == "off":
        await db.update_config({"notice_text": "OFF"})
        return await m.answer(
            "🔕 Auto-delete <b>notice band</b> — files ab bina notice ke delete hongi.\n"
            "(Auto-delete timer waisa hi chalega: /autodel)", parse_mode="HTML",
        )
    if text.lower() == "default":
        await db.update_config({"notice_text": ""})
        return await m.answer("✅ Notice <b>default text</b> pe wapas.", parse_mode="HTML")
    text = text[:1024]
    await db.update_config({"notice_text": text})
    cfg = await db.get_config()
    preview = core._notice_text(cfg, sent=1, is_batch=False)
    await m.answer(f"✅ <b>Notice text set!</b>\n\n<b>Preview:</b>\n{preview}", parse_mode="HTML")


@router.message(Command("setsupport"))
async def cmd_setsupport(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    import re
    arg = (command.args or "").strip()
    if not arg:
        cur = await db.get_support_users()
        listing = ", ".join("@" + u for u in cur) or "khali (default owner text dikhega)"
        return await m.answer(
            f"☎️ <b>Support team abhi:</b> {listing}\n\n"
            "Usage: <code>/setsupport @user1 @user2</code>\n"
            "<code>/setsupport off</code> — team hatao",
            parse_mode="HTML",
        )
    if arg.lower() == "off":
        await db.set_support_users([])
        return await m.answer("✅ Support team hata di — <code>/support</code> ab default owner text dikhayega.", parse_mode="HTML")
    users = list(dict.fromkeys(u.lower() for u in re.findall(r"@?([A-Za-z0-9_]{4,32})", arg)))
    if not users:
        return await m.answer("❌ Valid username nahi mila. Example: <code>/setsupport @vikubhai01</code>", parse_mode="HTML")
    await db.set_support_users(users)
    await m.answer(
        f"✅ <b>Support team set:</b> {', '.join('@' + u for u in users)}\n\n"
        "☎️ Support button ab /start aur har delivered file pe in logon ka link dikhayega.",
        reply_markup=keyboards.support_kb(users),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ─── Admin management ────────────────────────────────────────────────────────

@router.message(Command("addadmin"))
async def cmd_addadmin(m: Message, command: CommandObject, bot: Bot):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    arg = (command.args or "").strip()
    if not arg:
        return await m.answer("Usage: <code>/addadmin 123456789</code> ya <code>/addadmin @username</code>", parse_mode="HTML")
    if arg.lstrip("-").isdigit():
        uid = int(arg)
    elif arg.startswith("@"):
        try:
            chat = await bot.get_chat(arg)
        except Exception as e:
            return await m.answer(
                f"❌ {html.escape(arg)} resolve nahi hua.\n"
                "User ko bot me <b>/start</b> karke <b>/myid</b> bhejwao, phir ID se add karo:\n"
                "<code>/addadmin &lt;id&gt;</code>",
                parse_mode="HTML",
            )
        if chat.type != "private":
            return await m.answer("❌ Ye user nahi, chat hai — user ki numeric ID use karo.", parse_mode="HTML")
        uid = chat.id
    else:
        return await m.answer("Usage: <code>/addadmin 123456789</code> ya <code>/addadmin @username</code>", parse_mode="HTML")
    await db.bootstrap_admin(uid)
    await m.answer(f"✅ <b>Admin added!</b>\n👑 🆔 <code>{uid}</code> ab admin hai.", parse_mode="HTML")


@router.message(Command("admins"))
async def cmd_admins(m: Message):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    env_ids = sorted(config.ADMIN_IDS)
    db_ids = [int(i) for i in (await db.aget("settings/admin_ids") or [])]
    lines = ["👑 <b>Admin list:</b>\n"]
    for uid in env_ids:
        lines.append(f"• <code>{uid}</code> (env)")
    for uid in db_ids:
        if uid not in env_ids:
            lines.append(f"• <code>{uid}</code>")
    await m.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("deladmin"))
async def cmd_deladmin(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        return await m.answer("Usage: <code>/deladmin 123456789</code>", parse_mode="HTML")
    uid = int(arg)
    if uid in config.ADMIN_IDS:
        return await m.answer(
            "⚠️ Ye <b>env admin</b> hai — bot se nahi hatega.\n"
            "Coolify → Environment Variables → <code>ADMIN_IDS</code> se hatao.",
            parse_mode="HTML",
        )
    await db.remove_admin(uid)
    await m.answer(f"✅ Admin <code>{uid}</code> removed.", parse_mode="HTML")


# ─── Bans ────────────────────────────────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        return await m.answer("Usage: <code>/ban 123456789</code>", parse_mode="HTML")
    await db.set_banned(int(arg), True)
    await m.answer(f"🚫 User <code>{arg}</code> banned.", parse_mode="HTML")


@router.message(Command("unban"))
async def cmd_unban(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        return await m.answer("Usage: <code>/unban 123456789</code>", parse_mode="HTML")
    await db.set_banned(int(arg), False)
    await m.answer(f"✅ User <code>{arg}</code> unbanned.", parse_mode="HTML")


# ─── File mgmt ───────────────────────────────────────────────────────────────

@router.message(Command("delfile"))
async def cmd_delfile(m: Message, command: CommandObject):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    fid = (command.args or "").strip()
    if not fid:
        return await m.answer("Usage: <code>/delfile &lt;file_id&gt;</code>", parse_mode="HTML")
    f = await db.get_file(fid)
    if not f:
        return await m.answer("❌ File not found.", parse_mode="HTML")
    await db.delete_file(fid)
    await m.answer(f"🗑 File <code>{fid}</code> deleted (link ab dead hai).", parse_mode="HTML")


@router.message(Command("getfile"))
async def cmd_getfile(m: Message, command: CommandObject, bot: Bot):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    fid = (command.args or "").strip()
    f = await db.get_file(fid) if fid else None
    if not f:
        return await m.answer("❌ File not found. <code>/getfile &lt;file_id&gt;</code>", parse_mode="HTML")
    f["_id"] = fid
    await core.deliver_file(bot, m.from_user.id, f)


# ─── Stats ───────────────────────────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    users = await db.all_users()
    files = await db.all_files()
    batches = await db.all_batches()
    channels = await db.get_channels()
    clicks = sum((f or {}).get("clicks", 0) for f in files.values())
    banned = sum(1 for u in users.values() if u and u.get("banned"))
    up = int(time.time() - START_TIME)
    up_s = f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m" if up > 86400 else f"{up // 3600}h {up % 3600 // 60}m"
    await m.answer(
        f"📊 <b>Bot Stats</b>\n\n"
        f"👥 Users: <b>{len(users)}</b> (🚫 {banned} banned)\n"
        f"🗂 Files: <b>{len(files)}</b>\n"
        f"📦 Batches: <b>{len(batches)}</b>\n"
        f"🔗 File clicks: <b>{clicks}</b>\n"
        f"📢 Channels: <b>{len(channels)}</b>\n"
        f"⏱ Uptime: <b>{up_s}</b>",
        parse_mode="HTML",
    )


# ─── Broadcast ───────────────────────────────────────────────────────────────

def _bc_cb(chat: int, msg: int) -> str:
    return f"do:bc:{chat}:{msg}"


@router.message(Command("broadcast"))
async def cmd_broadcast(m: Message):
    if not await is_admin(m.from_user.id):
        return await deny(m)
    if not (m.reply_to_message):
        return await m.answer("Usage: jis message ko bhejna hai usko <b>reply</b> karke <code>/broadcast</code> likho.", parse_mode="HTML")
    users = await db.all_users()
    targets = [uid for uid, u in users.items() if not (u or {}).get("banned")]
    if not targets:
        return await m.answer("📭 Koi user nahi mila.")
    await m.answer(
        f"📣 <b>{len(targets)} users</b> ko broadcast karna hai?\nConfirm karo:",
        reply_markup=keyboards.confirm_kb(_bc_cb(m.reply_to_message.chat.id, m.reply_to_message.message_id)),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("do:bc:"))
async def cb_broadcast(c: CallbackQuery, bot: Bot):
    parts = c.data.split(":")
    src_chat, src_msg = int(parts[2]), int(parts[3])
    await c.answer("Broadcast started...")
    try:
        await c.message.edit_reply_markup(reply_markup=keyboards.remove_kb())
    except Exception:
        pass
    users = await db.all_users()
    targets = [int(uid) for uid, u in users.items() if not (u or {}).get("banned")]
    sent = failed = 0
    prog: Message | None = None
    for i, uid in enumerate(targets, 1):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=src_chat, message_id=src_msg)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            await asyncio.sleep(1.1)  # flood control
        if i % 100 == 0 or i == len(targets):
            try:
                text = f"📣 <b>Broadcast progress</b>\n✅ {sent} | ❌ {failed} | 🔄 {i}/{len(targets)}"
                if prog is None:
                    prog = await bot.send_message(c.from_user.id, text, parse_mode="HTML")
                else:
                    await prog.edit_text(text, parse_mode="HTML")
            except Exception:
                pass
    try:
        await prog.edit_text(f"📣 <b>Broadcast complete!</b>\n✅ Sent: {sent}\n❌ Failed: {failed}", parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data == "do:cancel")
async def cb_cancel(c: CallbackQuery):
    await c.answer("Cancelled", show_alert=False)
    try:
        await c.message.edit_reply_markup(reply_markup=keyboards.remove_kb())
    except Exception:
        pass
