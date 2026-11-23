# GOD X FILES Bot (@god_x_mods_files_bot)

File-hosting + force-subscribe Telegram bot (@DOWNLOADFILEM1NX_BOT jaisa): owner kisi bhi file host kare → share link milega → link pe click karne wale ko pehle configured channels join karne hote hain → **✅ Verify** dabate hi file milti hai.

## ✨ Features

**Users**
- 🔗 File link (`t.me/god_x_mods_files_bot?start=file_<id>`) → force-join → verify → instant delivery
- 📦 Batch links (`?start=batch_<id>`) — ek link me multiple files
- 📢 Har file pe auto **"Join Channel"** button (admin hide/unhide kar sakte hain)
- ☎️ **Support team** — `/support` ya Support button (har file + /start pe) → direct chat links
- ⚠️ Auto-delete notice — **admin custom text** set kar sakta hai (`{time}` placeholder ke saath)
- 🆔 `/myid`, `/help`, `/about`, `/support`

**Owner / Admin**
- 📤 Kisi bhi file (document/video/audio/photo/voice/animation/sticker) ko bot ko bhejo → turant share link
- 📦 `/batch` → files bhejo → `/done` → single batch link
- 🔐 `/addchannel @username | -100id` (ya channel post forward karke reply) — force-sub channels
- 📋 `/channels`, `/delchannel @user|id|index`
- 👁 `/autosub on|off` — files wala subscribe button hide/unhide
- 🛡 `/protect on|off` — forward/save block (protect_content)
- ⏱ `/autodel <seconds>` — files kitne sec baad auto-delete (0 = off, default 600)
- ⚠️ `/setnotice <text>` — auto-delete notice ka custom text (`{time}`/`{count}` placeholders, HTML allowed); `/setnotice default` = default text, `/setnotice off` = notice band
- ☎️ `/setsupport @user1 @user2` — support team (Support buttons inko link karenge); `/setsupport off`
- 👑 `/addadmin <id|@username>`, `/admins`, `/deladmin <id>` — admin management
- 📣 `/broadcast` (kisi message ko reply karke) — sab users ko, progress ke saath
- 📊 `/stats` — users, files, batches, clicks, uptime
- 🚫 `/ban <uid>` / `/unban <uid>`, 🗑 `/delfile <id>`, 📥 `/getfile <id>`
- 👋 `/welcome <text>` — custom start message
- 🔑 `/admin <secret>` — ADMIN_IDS env khali ho to pehla admin bootstrap (secret = `ADMIN_SECRET` env)

**Tech**
- Python 3.11 + aiogram 3 (polling) + Firebase RTDB (botdata subtree)
- file_id reuse — koi download/server storage nahi, unlimited scale
- Health endpoint on `$PORT` (Coolify/Koyeb healthchecks)
- Upload rate-limit, banned gate, flood-safe batch delivery

## 🚀 Deploy (Coolify / Docker)

1. Repo clone → Coolify "New Resource → Dockerfile" → repo select (branch `main`)
2. Port: `8080`
3. Env vars:

| Key | Value |
| --- | --- |
| BOT_TOKEN | Telegram bot token |
| ADMIN_SECRET | koi random secret (admin bootstrap ke liye) |
| FIREBASE_DB_URL | `https://<project>-default-rtdb.firebaseio.com` |
| FIREBASE_SERVICE_ACCOUNT_B64 | service-account JSON ka base64 (`base64 -w0 serviceAccountKey.json`) |
| UPDATES_CHANNEL | (optional) file-button channel @username |
| OWNER_NAME / BOT_NAME | branding |

4. Deploy → logs me `polling started — @<bot> live 🚀`

## 👤 Owner Quick Start (deploy ke baad)

1. Telegram me bot ko `/start` karo → `/myid` se apna ID dekho
2. `/admin <ADMIN_SECRET>` → tum admin ban jaoge
3. Bot ko apne channel(s) me **admin (invite users permission)** banao
4. `/addchannel @channelusername` → force-sub set
5. Bot ko koi file bhejo → link milega → usko share karo
6. Link tester: `/myid`, link click → join → ✅ Verify → file 📥
7. Buttons/settings: `/autosub off` (button hide), `/autodel 0` (auto-delete off), `/protect on`

## 🧪 Tests

```bash
pip install -r requirements.txt
python -m tests.test_logic   # unit tests (mocked Telegram) + live Firebase/Bot-API checks
```
