"""Inline keyboards."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def t_me_link(username: str, payload: str) -> str:
    return f"https://t.me/{username}?start={payload}"


def start_kb(updates_channel: str | None) -> InlineKeyboardMarkup:
    rows = []
    if updates_channel:
        rows.append([InlineKeyboardButton(text="📢 Join Updates Channel", url=f"https://t.me/{updates_channel}")])
    rows.append([InlineKeyboardButton(text="ℹ️ About", callback_data="about"),
                 InlineKeyboardButton(text="🆘 Help", callback_data="help"),
                 InlineKeyboardButton(text="☎️ Support", callback_data="support")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def force_sub_kb(channels: list[dict]) -> InlineKeyboardMarkup:
    """channels: [{chat_id, title, url}] — url is invite link or t.me/username."""
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton(text=f"📢 Join {ch['title'][:28]}", url=ch["url"])])
    rows.append([InlineKeyboardButton(text="✅ Verify & Get File ▶️", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def file_kb(updates_url: str | None) -> InlineKeyboardMarkup:
    """Buttons on delivered files: auto 'join channel' (hide/unhide via /autosub) + support row."""
    rows = []
    if updates_url:
        rows.append([InlineKeyboardButton(text="📢 Join Channel 🔗", url=updates_url)])
    rows.append([InlineKeyboardButton(text="☎️ Support", callback_data="support")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_kb(users: list[str]) -> InlineKeyboardMarkup:
    """Direct chat buttons for each support-team username."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"💬 @{u}", url=f"https://t.me/{u}")] for u in users]
    )


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm", callback_data=f"do:{action}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="do:cancel"),
    ]])


def remove_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[])
