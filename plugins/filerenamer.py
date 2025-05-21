import os
import time
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply, CallbackQuery
from helper.utils import is_req_admin, is_subscribed, get_size
from config import Config
from helper.database import db
from plugins.antinsfw import check_anti_nsfw # CORRECTED: Import check_anti_nsfw
from bot.rename_queue import RenameQueue

# Configure logging for the new filerenamer plugin
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get the singleton instance of the rename queue
rename_queue = RenameQueue.get_instance()

# Dictionary to store the original message for reply_to_message handling
user_pending_renames = {} # {user_id: original_message_id}

# Text for the /renamesource menu
RENAME_SOURCE_TEXT = """**Diablo Rename Bot 2:**
Choose the option below:

» **Caption:** Bot will check the caption of the file for renaming.
» **Filename:** Bot will check the original filename for renaming."""

# Command to bring up the rename source options
@Client.on_message(filters.private & filters.command("renamesource"))
async def rename_source_command(client: Client, message: Message):
    await message.reply_text(
        RENAME_SOURCE_TEXT,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Caption", callback_data="set_rename_source_caption")],
            [InlineKeyboardButton("Filename", callback_data="set_rename_source_filename")]
        ])
    )

# Callback queries for setting rename source
@Client.on_callback_query(filters.regex("^set_rename_source_"))
async def set_rename_source_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    source_type = query.data.replace("set_rename_source_", "") # Extracts 'caption' or 'filename'

    await db.set_rename_source(user_id, source_type) # Save to database
    await query.message.edit_text(f"✅ Rename source set to **`{source_type.capitalize()}`**.")

# Handle incoming file messages for renaming (pre-command)
@Client.on_message(filters.private & (filters.document | filters.video | filters.audio) & ~filters.command(["rename", "rename_file", "renamesource"]))
async def file_for_rename_handler(client: Client, message: Message):
    user_id = message.from_user.id

    # Check for force subscription
    if Config.FORCE_SUB_CHANNEL:
        try:
            invite_link = await client.create_chat_invite_link(Config.FORCE_SUB_CHANNEL)
            if not await is_subscribed(client, message, invite_link):
                return
        except Exception as e:
            logger.error(f"Force Sub Error for user {user_id}: {e}")
            await message.reply_text(
                "⚠️ Error with Force Subscribe channel. Please ensure the bot is an admin in the channel and the channel ID is correct in Config.",
                disable_web_page_preview=True
            )
            return

    # Store the message ID so /rename can reply to it
    user_pending_renames[user_id] = message.id
    logger.info(f"Stored message ID {message.id} for user {user_id} for pending rename.")

    # Get file type and name for display
    if message.document:
        file_name = message.document.file_name
        file_size = message.document.file_size
    elif message.video:
        file_name = message.video.file_name or "video_file"
        file_size = message.video.file_size
    elif message.audio:
        file_name = message.audio.file_name or "audio_file"
        file_size = message.audio.file_size
    else:
        file_name = "unknown_file"
        file_size = 0

    # Reply asking for the new name
    await message.reply_text(
        f"**📄 Original File:** `{file_name}` ({get_size(file_size)})\n\n"
        "Please send the **new file name** you want, or use the command `/rename` as a reply to this file.\n\n"
        "**Example:** `My Renamed Movie.mp4` (Just send the name, extension will be handled.)",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancel", callback_data="cancel_rename")]]
        )
    )

# Handle /rename or /rename_file command (either as a reply or with name in argument)
@Client.on_message(filters.private & filters.command(["rename", "rename_file"]))
async def initiate_rename_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check for force subscription
    if Config.FORCE_SUB_CHANNEL:
        try:
            invite_link = await client.create_chat_invite_link(Config.FORCE_SUB_CHANNEL)
            if not await is_subscribed(client, message, invite_link):
                return
        except Exception as e:
            logger.error(f"Force Sub Error for user {user_id}: {e}")
            await message.reply_text(
                "⚠️ Error with Force Subscribe channel. Please ensure the bot is an admin in the channel and the channel ID is correct in Config.",
                disable_web_page_preview=True
            )
            return

    original_file_message = None
    new_file_name = None

    # Case 1: Command used as a reply to a file
    if message.reply_to_message and (message.reply_to_message.document or message.reply_to_message.video or message.reply_to_message.audio):
        original_file_message = message.reply_to_message
        # Get new name from command arguments if provided
        if len(message.command) > 1:
            new_file_name = " ".join(message.command[1:])
        else:
            # If no name given in command, prompt user for name
            await message.reply_text(
                "Please send the **new file name** you want, or use `/rename <new name>` as a reply.",
                reply_markup=ForceReply(True)
            )
            return
            
    # Case 2: Command used without reply, but original file was sent just before
    elif user_id in user_pending_renames:
        original_message_id = user_pending_renames.pop(user_id)
        try:
            original_file_message = await client.get_messages(chat_id=user_id, message_ids=original_message_id)
            if not (original_file_message and (original_file_message.document or original_file_message.video or original_file_message.audio)):
                original_file_message = None
        except Exception:
            original_file_message = None

        if original_file_message and len(message.command) > 1:
            new_file_name = " ".join(message.command[1:])
        elif original_file_message:
            file_info = original_file_message.document or original_file_message.video or original_file_message.audio
            await message.reply_text(
                f"**Original File:** `{file_info.file_name or 'unknown_file'}`\n\n"
                "Please send the **new file name** you want, or use `/rename <new name>`.",
                reply_markup=ForceReply(True)
            )
            return
            
    # If no file is associated after all checks
    if not original_file_message:
        await message.reply_text("Please reply to a **document, video, or audio file** with `/rename <new name>`, or send the file first then send the new name.")
        return

    # Get media and file_id
    media = original_file_message.document or original_file_message.video or original_file_message.audio
    if not media:
        await message.reply_text("Could not find media in the message to rename.")
        return

    file_id = media.file_id

    if new_file_name is None:
        if message.reply_to_message and message.reply_to_message.from_user.id == client.me.id:
            new_file_name = message.text
            original_message_id = user_pending_renames.get(user_id)
            if not original_message_id:
                    await message.reply_text("Seems like you didn't send the file before sending the name. Please send the file first!")
                    return
            try:
                original_file_message = await client.get_messages(chat_id=user_id, message_ids=original_message_id)
                if not (original_file_message and (original_file_message.document or original_file_message.video or original_file_message.audio)):
                    original_file_message = None
            except Exception:
                original_file_message = None
            if not original_file_message:
                await message.reply_text("I couldn't find the original file to rename. Please send the file again and then the new name.")
                return
        else:
            await message.reply_text("Please reply to a **document, video, or audio file** with `/rename <new name>`, or send the file first then send the new name.")
            return

    if not new_file_name:
        await message.reply_text("Please provide a new file name.")
        return

    # --- START OF DAILY LIMIT AND PREMIUM CHECK ---
    is_premium = await db.is_premium_user(user_id)

    if not is_premium:
        current_count, user_limit = await db.get_daily_rename_count(user_id)
        if user_limit == -1:
             logger.warning(f"Non-premium user {user_id} has an unlimited limit (-1). Skipping daily limit check.")
        elif current_count >= user_limit:
            await message.reply_text(
                f"**Daily Limit Reached!** 🚫\n\n"
                f"You have used your daily limit of **{user_limit}** file renames.\n"
                "Please wait for tomorrow to rename more files.\n\n"
                "✨ Upgrade to **premium** for **unlimited** renames! /premium"
            )
            logger.info(f"User {user_id} (non-premium) reached daily limit ({user_limit}). Current count: {current_count}.")
            return

    # Check for NSFW content *before* adding to queue
    # Now using the single check_anti_nsfw function
    if await check_anti_nsfw(new_file_name, message): # Pass new_file_name and message
        return # check_anti_nsfw already sends the reply message

    # Add user to DB if not exists
    await db.add_user(client, message)

    # Get rename source preference for this user
    rename_source_pref = await db.get_rename_source(user_id)

    # Convert original_file_message to a dictionary for safe passing to queue
    message_dict = {
        "id": original_file_message.id,
        "chat": {"id": original_file_message.chat.id},
        "caption": original_file_message.caption if original_file_message.caption else None,
        "document": original_file_message.document.to_dict() if original_file_message.document else None,
        "video": original_file_message.video.to_dict() if original_file_message.video else None,
        "audio": original_file_message.audio.to_dict() if original_file_message.audio else None,
        "photo": original_file_message.photo[0].to_dict() if original_file_message.photo else None,
        "file_size": media.file_size
    }

    # Add the task to the renaming queue
    success, queue_status_msg = await rename_queue.add_to_queue(
        user_id,
        message_dict,
        file_id,
        new_file_name,
        rename_source_pref
    )

    if success:
        await message.reply_text(queue_status_msg)
        if not is_premium:
            await db.increment_daily_rename_count(user_id)
            logger.info(f"Incremented rename count for non-premium user {user_id}. File: {new_file_name}")

        position, total = await rename_queue.get_user_queue_position(user_id)
        if position > 0:
            await message.reply_text(f"Your position in queue: **{position}/{total}**")
    else:
        await message.reply_text(queue_status_msg)

# Callback for cancelling rename operation
@Client.on_callback_query(filters.regex("^cancel_rename$"))
async def cancel_rename_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    if user_id in user_pending_renames:
        del user_pending_renames[user_id]
        await query.edit_message_text("🚫 Rename operation cancelled.")
    else:
        await query.answer("No pending rename operation to cancel.", show_alert=False)

# Command to check queue status (for bot owner)
@Client.on_message(filters.private & filters.command("queuestatus"))
async def get_queue_status_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check if admin
    if user_id not in Config.ADMIN:
        await message.reply_text("This command is for bot owners/admins only.")
        return

    status_msg = rename_queue.get_queue_status()
    await message.reply_text(status_msg)
