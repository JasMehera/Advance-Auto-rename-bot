from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from helper.database import db # THIS LINE IS CHANGED: from 'codeflixbots' to 'db'

@Client.on_message(filters.private & filters.command("autorename"))
async def auto_rename_command(client, message):
    user_id = message.from_user.id
    
    # Check if user is premium
    is_premium = await db.is_premium_user(user_id) # THIS LINE IS CHANGED
    
    if not is_premium:
        return await message.reply_text(
            "❌ **Premium Feature** ❌\n\n"
            "File renaming is a premium feature.\n"
            "Contact @Union_Owner to rename files."
        )

    # Extract and validate the format from the command
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        await message.reply_text(
            "**Please provide a new name after the command /autorename**\n\n"
            "Here's how to use it:\n"
            "**Example format:** `/autorename Overflow [S{season}E{episode}] - [Dual] {quality}`"
        )
        return

    format_template = command_parts[1].strip()

    # Save the format template in the database
    await db.set_format_template(user_id, format_template) # THIS LINE IS CHANGED

    # Send confirmation message with the template in monospaced font
    await message.reply_text(
        f"**🌟 Fantastic! You're ready to auto-rename your files.**\n\n"
        "📩 Simply send the file(s) you want to rename.\n\n"
        f"**Your saved template:** `{format_template}`\n\n"
        "Remember, it might take some time, but I'll ensure your files are renamed perfectly!✨"
    )


@Client.on_message(filters.private & filters.command("setmedia"))
async def set_media_command(client, message):
    """Initiate media type selection with a sleek inline keyboard."""
    user_id = message.from_user.id
    
    # Check if user is premium
    is_premium = await db.is_premium_user(user_id) # THIS LINE IS CHANGED
    
    if not is_premium:
        return await message.reply_text(
            "❌ **Premium Feature** ❌\n\n"
            "Media type selection is a premium feature.\n"
            "Contact @Union_Owner to get premium access."
        )
        
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Documents", callback_data="setmedia_document")],
        [InlineKeyboardButton("🎬 Videos", callback_data="setmedia_video")],
        [InlineKeyboardButton("🎵 Audio", callback_data="setmedia_audio")],  # Added audio option
    ])

    await message.reply_text(
        "✨ **Choose Your Media Vibe** ✨\n"
        "Select the type of media you'd like to set as your preference:",
        reply_markup=keyboard,
        quote=True
    )

@Client.on_callback_query(filters.regex(r"^setmedia_"))
async def handle_media_selection(client, callback_query: CallbackQuery):
    """Process the user's media type selection with flair and confirmation."""
    user_id = callback_query.from_user.id
    
    # Check if user is premium
    is_premium = await db.is_premium_user(user_id) # THIS LINE IS CHANGED
    
    if not is_premium:
        await callback_query.answer("This is a premium feature", show_alert=True)
        return await callback_query.message.edit_text(
            "❌ **Premium Feature** ❌\n\n"
            "Media type selection is a premium feature.\n"
            "Contact @Union_Owner to get premium access."
        )
        
    media_type = callback_query.data.split("_", 1)[1].capitalize()  # Extract and capitalize media type

    try:
        await db.set_media_preference(user_id, media_type.lower()) # THIS LINE IS CHANGED

        await callback_query.answer(f"Locked in: {media_type} 🎉")
        await callback_query.message.edit_text(
            f"🎯 **Media Preference Updated** 🎯\n"
            f"Your vibe is now set to: **{media_type}** ✅\n"
            f"Ready to roll with your choice!"
        )
    except Exception as e:
        await callback_query.answer("Oops, something went wrong! 😅")
        await callback_query.message.edit_text(
            f"⚠️ **Error Setting Preference** ⚠️\n"
            f"Couldn't set {media_type} right now. Try again later!\n"
            f"Details: {str(e)}"
        )
