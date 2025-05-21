import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from helper.database import db # Assuming your database instance is named 'db'
from config import Config # Assuming your Config class contains ADMINS

@Client.on_message(filters.command("my_limit") & filters.private & filters.incoming)
async def my_limit(client: Client, message: Message):
    """
    Allows a user to check their current rename limit.
    """
    user_id = message.from_user.id

    is_premium = await db.is_premium_user(user_id)
    if is_premium:
        return await message.reply_text(
            "✨ **You are a Premium User!** ✨\n\nYou have **unlimited** renames."
        )

    user_data = await db.get_user_data(user_id)
    renames_today = user_data.get("renames_today", 0)
    daily_limit = user_data.get("daily_rename_limit", Config.DEFAULT_DAILY_RENAME_LIMIT)

    reset_time_str = user_data.get("rename_reset_time")
    reset_message = "Your limit will reset automatically at midnight IST."
    if reset_time_str:
        try:
            # Parse the stored time as UTC, then convert to IST
            reset_time_utc = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
            # Adjust to IST (UTC+5:30)
            reset_time_ist = reset_time_utc + timedelta(hours=5, minutes=30)
            reset_message = f"Your limit will reset at **{reset_time_ist.strftime('%I:%M %p IST')}**."
        except ValueError:
            reset_message = "Your limit will reset automatically at midnight IST."


    remaining_renames = max(0, daily_limit - renames_today)

    await message.reply_text(
        f"📊 **Your Daily Rename Limit:**\n"
        f"You have used **{renames_today}** out of **{daily_limit}** renames today.\n"
        f"You have **{remaining_renames}** renames remaining.\n\n"
        f"_{reset_message}_"
    )


@Client.on_message(filters.command("set_limit") & filters.user(Config.ADMINS) & filters.private)
async def set_limit(client: Client, message: Message):
    """
    Admin command to set a custom daily rename limit for a user.
    Usage: /set_limit <user_id> <limit>
    """
    if len(message.command) != 3:
        return await message.reply_text("Usage: `/set_limit <user_id> <limit>`\nExample: `/set_limit 123456 10`")

    try:
        user_id = int(message.command[1])
        limit = int(message.command[2])
    except ValueError:
        return await message.reply_text("Invalid User ID or Limit. Please use numbers.")

    if limit < 0:
        return await message.reply_text("Limit cannot be negative.")

    await db.set_daily_rename_limit(user_id, limit)
    await message.reply_text(f"Daily rename limit for user `{user_id}` set to **{limit}**.")


@Client.on_message(filters.command("add_premium") & filters.user(Config.ADMINS) & filters.private)
async def add_premium(client: Client, message: Message):
    """
    Admin command to grant premium status to a user.
    Usage: /add_premium <user_id>
    """
    if len(message.command) != 2:
        return await message.reply_text("Usage: `/add_premium <user_id>`\nExample: `/add_premium 123456`")

    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid User ID. Please use a number.")

    await db.add_premium_user(user_id)
    await message.reply_text(f"User `{user_id}` has been granted **Premium** status.")


@Client.on_message(filters.command("remove_premium") & filters.user(Config.ADMINS) & filters.private)
async def remove_premium(client: Client, message: Message):
    """
    Admin command to revoke premium status from a user.
    Usage: /remove_premium <user_id>
    """
    if len(message.command) != 2:
        return await message.reply_text("Usage: `/remove_premium <user_id>`\nExample: `/remove_premium 123456`")

    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid User ID. Please use a number.")

    await db.remove_premium_user(user_id)
    await message.reply_text(f"User `{user_id}` has had **Premium** status revoked.")
