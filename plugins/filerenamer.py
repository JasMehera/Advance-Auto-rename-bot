import os
import time
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply, CallbackQuery
from helper.utils import is_req_admin, is_subscribed, get_size # RE-ADDED is_req_admin and is_subscribed
from config import Config
from helper.database import db # Correctly imports your Database instance named 'db'
from plugins.antinsfw import nsfw_detect_video, nsfw_detect_image
from bot.rename_queue import RenameQueue # Import the queue manager

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

    # Check for force subscription - NOW USING THE is_subscribed FROM helper.utils
    if Config.FORCE_SUB_CHANNEL: # Assuming Config.FORCE_SUB_CHANNEL is a single ID
        try:
            invite_link = await client.create_chat_invite_link(Config.FORCE_SUB_CHANNEL)
            if not await is_subscribed(client, message, invite_link): # UNCOMMENTED
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
    
    # Check for force subscription - NOW USING THE is_subscribed FROM helper.utils
    if Config.FORCE_SUB_CHANNEL:
        try:
            invite_link = await client.create_chat_invite_link(Config.FORCE_SUB_CHANNEL)
            if not await is_subscribed(client, message, invite_link): # UNCOMMENTED
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
                reply_markup=ForceReply(True) # Force reply to get the name
            )
            return
            
    # Case 2: Command used without reply, but original file was sent just before
    elif user_id in user_pending_renames:
        original_message_id = user_pending_renames.pop(user_id) # Get and clear pending status
        try:
            original_file_message = await client.get_messages(chat_id=user_id, message_ids=original_message_id)
            if not (original_file_message and (original_file_message.document or original_file_message.video or original_file_message.audio)):
                original_file_message = None # Not a valid media message
        except Exception:
            original_file_message = None

        if original_file_message and len(message.command) > 1:
            new_file_name = " ".join(message.command[1:])
        elif original_file_message: # If original file was there, but no name in command
            file_info = original_file_message.document or original_file_message.video or original_file_message.audio
            await message.reply_text(
                f"**Original File:** `{file_info.file_name or 'unknown_file'}`\n\n"
                "Please send the **new file name** you want, or use `/rename <new name>`.",
                reply_markup=ForceReply(True) # Force reply to get the name
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

    # If new_file_name is still None, it means the user was prompted for it in the previous step
    # and this handler is being called by the forced reply.
    if new_file_name is None:
        # Check if this message is a reply to our bot's prompt
        if message.reply_to_message and message.reply_to_message.from_user.id == client.me.id:
            # Assume this is the new name sent by the user
            new_file_name = message.text
            original_message_id = user_pending_renames.get(user_id) # Get it back from pending, or set it to None if not there
            if not original_message_id: # This should not happen if logic is followed
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
        else: # Unhandled case, user just sent /rename without proper context
            await message.reply_text("Please reply to a **document, video, or audio file** with `/rename <new name>`, or send the file first then send the new name.")
            return

    if not new_file_name:
        await message.reply_text("Please provide a new file name.")
        return

    # --- START OF DAILY LIMIT AND PREMIUM CHECK ---
    is_premium = await db.is_premium_user(user_id)

    if not is_premium:
        # For non-premium users, check daily rename limit
        current_count, user_limit = await db.get_daily_rename_count(user_id)

        # -1 indicates unlimited, but we are only here for non-premium, so a negative limit implies an error
        if user_limit == -1: # This shouldn't happen for non-premium if logic is followed
             logger.warning(f"Non-premium user {user_id} has an unlimited limit (-1). Skipping daily limit check.")
        elif current_count >= user_limit:
            # If the limit is reached, inform the user and stop
            await message.reply_text(
                f"**Daily Limit Reached!** 🚫\n\n"
                f"You have used your daily limit of **{user_limit}** file renames.\n"
                "Please wait for tomorrow to rename more files.\n\n"
                "✨ Upgrade to **premium** for **unlimited** renames! /premium"
            )
            logger.info(f"User {user_id} (non-premium) reached daily limit ({user_limit}). Current count: {current_count}.")
            return # Stop processing this file

    # --- END OF DAILY LIMIT AND PREMIUM CHECK ---

    # Check for NSFW content *before* adding to queue to save resources
    is_nsfw = False
    if original_file_message.video or (original_file_message.document and media.mime_type and media.mime_type.startswith('video/')):
        is_nsfw, nsfw_score = await nsfw_detect_video(original_file_message.video or original_file_message.document)
    elif original_file_message.document and media.mime_type and media.mime_type.startswith('image/'):
        is_nsfw, nsfw_score = await nsfw_detect_image(original_file_message.document)
    elif original_file_message.photo: # Added for photo messages
        is_nsfw, nsfw_score = await nsfw_detect_image(original_file_message.photo)
    
    if is_nsfw:
        await message.reply_text(f"🔞 NSFW content detected ({nsfw_score:.2f}%). Renaming is not allowed.")
        return

    # Add user to DB if not exists (good practice before operations)
    # The add_user method in your database.py requires `b` (client) and `m` (message)
    # So assuming `b` is `client` and `m` is `message` here:
    await db.add_user(client, message)


    # Get rename source preference for this user
    rename_source_pref = await db.get_rename_source(user_id) # Default to 'filename' if not set

    # Convert original_file_message to a dictionary for safe passing to queue
    message_dict = {
        "id": original_file_message.id,
        "chat": {"id": original_file_message.chat.id},
        "caption": original_file_message.caption if original_file_message.caption else None,
        "document": original_file_message.document.to_dict() if original_file_message.document else None, # Convert to dict
        "video": original_file_message.video.to_dict() if original_file_message.video else None, # Convert to dict
        "audio": original_file_message.audio.to_dict() if original_file_message.audio else None, # Convert to dict
        "photo": original_file_message.photo[0].to_dict() if original_file_message.photo else None, # Convert photo to dict (take largest size)
        "file_size": media.file_size # Include file_size in dict
    }

    # Add the task to the renaming queue
    success, queue_status_msg = await rename_queue.add_to_queue(
        user_id,
        message_dict,
        file_id,
        new_file_name,
        rename_source_pref # Pass the selected rename source
    )

    if success:
        await message.reply_text(queue_status_msg)
        # Only increment for non-premium users if successfully added to queue
        if not is_premium:
            await db.increment_daily_rename_count(user_id)
            logger.info(f"Incremented rename count for non-premium user {user_id}. File: {new_file_name}")

        # Optionally, show queue position (ensure get_user_queue_position exists in rename_queue)
        position, total = await rename_queue.get_user_queue_position(user_id)
        if position > 0:
            await message.reply_text(f"Your position in queue: **{position}/{total}**")
    else:
        await message.reply_text(queue_status_msg) # e.g., "Too many files in queue"

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
    if user_id not in Config.ADMIN: # Use Config.ADMIN which is a list
        await message.reply_text("This command is for bot owners/admins only.")
        return

    status_msg = rename_queue.get_queue_status()
    await message.reply_text(status_msg)
