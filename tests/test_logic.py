"""Logic tests: pure functions, DB layer (isolated botdata_test subtree),
force-sub gating + delivery (FakeBot), live Bot API getMe.

Run: python -m tests.test_logic
"""
import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import config
import core
import db
import keyboards

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


# ─── Fake Telegram objects ───────────────────────────────────────────────────

class FakeBot:
    """Records calls; returns canned member states."""
    def __init__(self, member_status_by_chat: dict | None = None):
        self.calls: list[tuple] = []
        self.messages: list[types.SimpleNamespace] = []
        self._status = {int(k): v for k, v in (member_status_by_chat or {}).items()}
        self.id = 777000001
        self.username = "god_x_mods_files_bot"

    async def get_me(self):
        return SimpleNamespace(id=self.id, username=self.username)

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self._status.get(int(chat_id), "left"), is_member=False)

    def _rec(self, method, **kw):
        msg = SimpleNamespace(message_id=100 + len(self.messages), **{k: v for k, v in kw.items() if k in ("chat_id",)})
        self.messages.append(SimpleNamespace(method=method, kwargs=kw))
        self.calls.append((method, kw))
        return msg

    async def send_document(self, **kw): return self._rec("send_document", **kw)
    async def send_video(self, **kw): return self._rec("send_video", **kw)
    async def send_photo(self, **kw): return self._rec("send_photo", **kw)
    async def send_audio(self, **kw): return self._rec("send_audio", **kw)
    async def send_voice(self, **kw): return self._rec("send_voice", **kw)
    async def send_animation(self, **kw): return self._rec("send_animation", **kw)
    async def send_sticker(self, **kw): return self._rec("send_sticker", **kw)
    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("send_message", {"chat_id": chat_id, "text": text}))
        return SimpleNamespace(message_id=200 + len(self.messages))
    async def delete_message(self, chat_id, message_id): return True


def fake_message(ftype: str = "document") -> SimpleNamespace:
    """aiogram-Message-like object for extract_file()."""
    doc = SimpleNamespace(file_id="FAKEFILEID123", file_name="godx_mods.zip", file_size=5242880)
    m = SimpleNamespace(
        document=doc if ftype == "document" else None,
        video=SimpleNamespace(file_id="VID1", file_name="clip.mp4", file_size=999) if ftype == "video" else None,
        audio=None, voice=None, animation=None, sticker=None,
        photo=[SimpleNamespace(file_id="PH1", file_size=4321)] if ftype == "photo" else None,
        caption="God X MODS premium file 🎁",
    )
    return m


TEST_CFG = {"autosub_button": True, "protect": False, "autodel_sec": 0}
TEST_CHANNELS = {"-1001234567890": {"title": "GOD X MODS", "username": "godxmods", "invite_link": ""}}
TEST_CHANNELS_PRIVATE = {"-1009876543210": {"title": "Private Ch", "username": "", "invite_link": "https://t.me/+abc"}}


# ─── 1. Pure logic ───────────────────────────────────────────────────────────

def test_pure():
    print("\n[1] Pure logic")
    check("parse file_", core.parse_payload("file_ABC123") == ("file", "ABC123"))
    check("parse batch_", core.parse_payload("batch_X9") == ("batch", "X9"))
    check("parse garbage", core.parse_payload("hello") is None)
    check("parse empty tail", core.parse_payload("file_") is None)

    check("human_size MB", core.human_size(5242880) == "5.0 MB")
    check("human_size None", core.human_size(None) == "?")

    ftype, fid, fname, fsize = core.handlers_extract(fake_message())
    check("extract document", (ftype, fid, fname) == ("document", "FAKEFILEID123", "godx_mods.zip"), str((ftype, fid)))
    ftype, fid, fname, fsize = core.handlers_extract(fake_message("photo"))
    check("extract photo", ftype == "photo" and fid == "PH1")

    kb = keyboards.force_sub_kb([{"chat_id": 1, "title": "A", "url": "https://t.me/a"},
                                 {"chat_id": 2, "title": "B", "url": "https://t.me/b"}])
    check("force_sub_kb rows", len(kb.inline_keyboard) == 3 and kb.inline_keyboard[-1][0].callback_data == "verify")

    check("file_kb None when no url", keyboards.file_kb(None) is None)
    kb = keyboards.file_kb("https://t.me/godxmods")
    check("file_kb join button", kb.inline_keyboard[0][0].text == "📢 Join Channel 🔗")

    limited = any(core.rate_limited(5550001) for _ in range(config.UPLOAD_RATE_LIMIT + 1))
    check("rate limit trips after N", limited)


# ─── 2. DB layer (isolated subtree) ──────────────────────────────────────────

async def test_db():
    print("\n[2] DB layer (botdata_test)")
    config.DB_ROOT = "botdata_test"
    try:
        fid = await db.unique_id("files")
        check("unique_id non-empty", bool(fid))
        await db.save_file(fid, {"file_id": "FID1", "ftype": "document", "caption": "cap", "fname": "a.zip", "fsize": 10, "owner_id": 1})
        f = await db.get_file(fid)
        check("save/get file", f and f["file_id"] == "FID1" and f["clicks"] == 0 and "created_at" in f)
        await db.add_click(fid)
        f = await db.get_file(fid)
        check("add_click", f["clicks"] == 1)

        bid = await db.unique_id("batches")
        await db.save_batch(bid, [fid, "f2"], 42)
        b = await db.get_batch(bid)
        check("save/get batch", b and b["ids"] == [fid, "f2"] and b["owner_id"] == 42)

        await db.upsert_user(777000123, "Test User", "testuser")
        u = await db.get_user(777000123)
        check("upsert/get user", u and u["name"] == "Test User" and u["username"] == "testuser" and "joined_at" in u)

        await db.set_banned(777000123, True)
        check("ban flag", (await db.get_user(777000123))["banned"] is True)
        await db.set_banned(777000123, False)

        await db.save_channel(-1001111, {"title": "T1", "username": "t1", "invite_link": "", "added_by": 1, "added_at": 0})
        await db.save_channel(-1002222, {"title": "T2", "username": "", "invite_link": "https://t.me/+x", "added_by": 1, "added_at": 0})
        chs = await db.get_channels()
        check("channels saved", len(chs) == 2)
        await db.delete_channel(-1002222)
        check("channel deleted", len(await db.get_channels()) == 1)

        cfg = await db.get_config()
        check("config defaults", cfg["autosub_button"] is True and cfg["protect"] is False and cfg["autodel_sec"] == config.AUTO_DELETE_SECONDS)

        await db.save_pending(777000123, "file", fid)
        p = await db.pop_pending(777000123)
        check("pending save/pop", p and p["type"] == "file" and p["id"] == fid)
        check("pending cleared", (await db.pop_pending(777000123)) is None)

        await db.bootstrap_admin(777000123)
        check("bootstrap admin", 777000123 in await db.all_admin_ids() or 777000123 in config.ADMIN_IDS)

        await db.delete_file(fid)
        check("file deleted", (await db.get_file(fid)) is None)
    finally:
        await db.adelete("")  # wipe botdata_test root
        config.DB_ROOT = "botdata"


# ─── 3. Force-sub gating (FakeBot) ───────────────────────────────────────────

async def test_force_sub():
    print("\n[3] Force-sub gating + delivery (FakeBot)")
    bot_joined = FakeBot({"-1001234567890": "member"})
    bot_not = FakeBot({"-1001234567890": "left"})
    with patch.object(db, "get_channels", return_value=dict(TEST_CHANNELS)):
        nj = await core.not_joined_channels(bot_joined, 1)
        check("member → no gate", nj == [], str(nj))
        nj = await core.not_joined_channels(bot_not, 1)
        check("left → gated", len(nj) == 1 and nj[0]["url"] == "https://t.me/godxmods")

    with patch.object(db, "get_channels", return_value=dict(TEST_CHANNELS_PRIVATE)):
        nj = await core.not_joined_channels(FakeBot({"-1009876543210": "left"}), 1)
        check("private channel uses invite_link", nj and nj[0]["url"] == "https://t.me/+abc")


async def test_delivery():
    print("\n[4] Delivery (FakeBot)")
    bot = FakeBot()
    f = {"_id": "TESTFID", "file_id": "FID1", "ftype": "document", "caption": "cap", "fname": "a.zip", "fsize": 10}
    with patch.object(db, "get_config", return_value=dict(TEST_CFG)), \
         patch.object(db, "get_channels", return_value=dict(TEST_CHANNELS)), \
         patch.object(db, "add_click", return_value=None):
        ok = await core.deliver_file(bot, 4242, f)
    check("file delivered", ok)
    doc_calls = [c for c in bot.calls if c[0] == "send_document"]
    check("send_document with file_id", doc_calls and doc_calls[0][1].get("document") == "FID1")
    check("auto-sub button attached", doc_calls and doc_calls[0][1].get("reply_markup") is not None)
    check("protect_content False", doc_calls and doc_calls[0][1].get("protect_content") is False)
    check("no autodel notice (sec=0)", not any(c[0] == "send_message" for c in bot.calls))

    bot2 = FakeBot()
    cfg2 = dict(TEST_CFG, autodel_sec=600)
    with patch.object(db, "get_config", return_value=cfg2), \
         patch.object(db, "get_channels", return_value=dict(TEST_CHANNELS)), \
         patch.object(db, "add_click", return_value=None):
        await core.deliver_file(bot2, 4242, f)
    warns = [c for c in bot2.calls if c[0] == "send_message" and "Auto-Delete" in c[1].get("text", "")]
    check("autodel warning sent", bool(warns))

    bot3 = FakeBot()
    with patch.object(db, "get_config", return_value=dict(TEST_CFG)), \
         patch.object(db, "get_batch", return_value={"ids": ["a", "b"], "owner_id": 1}), \
         patch.object(db, "get_file", side_effect=lambda fid: {"_id": fid, "file_id": f"FID-{fid}", "ftype": "video", "caption": "", "fname": None, "fsize": 1}), \
         patch.object(db, "get_channels", return_value=dict(TEST_CHANNELS)), \
         patch.object(db, "add_click", return_value=None):
        sent = await core.deliver_batch(bot3, 4242, ["a", "b"])
    check("batch delivered 2", sent == 2)
    vids = [c for c in bot3.calls if c[0] == "send_video"]
    check("batch videos via file_id", len(vids) == 2 and vids[0][1].get("video") == "FID-a")

    bot4 = FakeBot()
    with patch.object(db, "get_file", return_value=None):
        ok = await core.deliver_payload(bot4, 1, "file", "missing")
    check("dead link → message, False", ok is False and any("Invalid or expired" in c[1]["text"] for c in bot4.calls if c[0] == "send_message"))


# ─── 4. Live Telegram Bot API ────────────────────────────────────────────────

async def test_live():
    print("\n[5] Live Bot API (token validity)")
    if not config.BOT_TOKEN or "your-bot-token" in config.BOT_TOKEN:
        print("  ⏭ skipped (no real token in env)")
        return
    from aiogram import Bot
    bot = Bot(config.BOT_TOKEN)
    try:
        me = await bot.get_me()
        check("getMe", bool(me.username), me.username or "")
        print(f"     → live bot: @{me.username} (id={me.id})")
        if config.BOT_USERNAME and me.username != config.BOT_USERNAME:
            print(f"     ⚠️ username mismatch vs env ({config.BOT_USERNAME})")
        else:
            check("username matches env", True)
    finally:
        await bot.session.close()


async def main():
    if config.validate():
        print("CONFIG ERRORS:", config.validate())
        sys.exit(1)
    db.init()
    test_pure()
    await test_db()
    await test_force_sub()
    await test_delivery()
    await test_live()
    print(f"\n{'='*40}\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


# handlers.py import check (wiring)
def test_imports():
    print("\n[0] Module imports (wiring)")
    import admin  # noqa
    import bot  # noqa
    import handlers  # noqa
    check("handlers/admin/bot import clean", True)
    core.handlers_extract = handlers.extract_file  # bind for pure tests
    core.human_size = handlers.human_size


if __name__ == "__main__":
    test_imports()
    asyncio.run(main())
