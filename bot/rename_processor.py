import os
import re
import time
import shutil
import asyncio
import logging
from datetime import datetime
from PIL import Image
from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaDocument, Message
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from helper.utils import progress_for_pyrogram, humanbytes, convert
from helper.database import db # Make sure this imports your Database instance named 'db'
from config import Config
from pymongo import MongoClient
from typing import Dict, Any, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection for checking sequence mode
db_client = MongoClient(Config.DB_URL)
db_mongo = db_client[Config.DB_NAME] # Renamed to avoid conflict with `helper.database.db`
sequence_collection = db_mongo["active_sequences"]

# Enhanced regex patterns for season and episode extraction
SEASON_EPISODE_PATTERNS = [
    # Standard patterns (S01E02, S01EP02)
    (re.compile(r'S(\d+)(?:E|EP)(\d+)'), ('season', 'episode')),
    # Patterns with spaces/dashes (S01 E02, S01-EP02)
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)'), ('season', 'episode')),
    # Full text patterns (Season 1 Episode 2)
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    # Patterns with brackets/parentheses ([S01][E02])
    (re.compile(r'\[S(\d+)\]\[E(\d+)\]'), ('season', 'episode')),
    # Fallback patterns (S01 13, Episode 13)
    (re.compile(r'S(\d+)[^\d]*(\d+)'), ('season', 'episode')),
    (re.compile(r'(?:E|EP|Episode)\s*(\d+)', re.IGNORECASE), (None, 'episode')),
    # Final fallback (standalone number)
    (re.compile(r'\b(\d+)\b'), (None, 'episode'))
]

# Quality detection patterns
QUALITY_PATTERNS = [
    (re.compile(r'\b(\d{3,4}[pi])\b', re.IGNORECASE), lambda m: m.group(1)),  # 1080p, 720p
    (re.compile(r'\b(4k|2160p)\b', re.IGNORECASE), lambda m: "4k"),
    (re.compile(r'\b(2k|1440p)\b', re.IGNORECASE), lambda m: "2k"),
    (re.compile(r'\b(HDRip|HDTV)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\b(4kX264|4kx265)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\[(\d{3,4}[pi])\]', re.IGNORECASE), lambda m: m.group(1))   # [1080p]
]

def is_in_sequence_mode(user_id):
    """Check if user is in sequence mode"""
    return sequence_collection.find_one({"user_id": user_id}) is not None

def extract_season_episode(filename):
    """Extract season and episode numbers from filename"""
    for pattern, (season_group, episode_group) in SEASON_EPISODE_PATTERNS:
        match = pattern.search(filename)
        if match:
            season = match.group(1) if season_group else None
            episode = match.group(2) if episode_group else match.group(1)
            logger.info(f"Extracted season: {season}, episode: {episode} from {filename}")
            return season, episode
    logger.warning(f"No season/episode pattern matched for {filename}")
    return None, None

def extract_quality(filename):
    """Extract quality information from filename"""
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(filename)
        if match:
            quality = extractor(match)
            logger.info(f"Extracted quality: {quality} from {filename}")
            return quality
    logger.warning(f"No quality pattern matched for {filename}")
    return "Unknown"

async def cleanup_files(*paths):
    """Safely remove files if they exist"""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Error removing {path}: {e}")

async def process_thumbnail(thumb_path):
    """Process and resize thumbnail image"""
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    
    try:
        with Image.open(thumb_path) as img:
            img = img.convert("RGB").resize((320, 320))
            img.save(thumb_path, "JPEG")
        return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail processing failed: {e}")
        await cleanup_files(thumb_path)
        return None

async def add_metadata(input_path, output_path, user_id):
    """Add metadata to media file using ffmpeg"""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        logger.warning("FFmpeg not found in PATH, skipping metadata addition")
        # Just copy the file instead of adding metadata
        try:
            shutil.copy2(input_path, output_path)
            return
        except Exception as e:
            logger.error(f"Error copying file: {e}")
            raise RuntimeError(f"Failed to process file: {e}") # Re-raise to indicate failure
            
    metadata = {
        'title': await db.get_title(user_id),
        'artist': await db.get_artist(user_id),
        'author': await db.get_author(user_id),
        'video_title': await db.get_video(user_id),
        'audio_title': await db.get_audio(user_id),
        'subtitle': await db.get_subtitle(user_id)
    }
    
    cmd = [
        ffmpeg,
        '-i', input_path,
        '-metadata', f'title={metadata["title"]}',
        '-metadata', f'artist={metadata["artist"]}',
        '-metadata', f'author={metadata["author"]}',
        '-metadata:s:v', f'title={metadata["video_title"]}',
        '-metadata:s:a', f'title={metadata["audio_title"]}',
        '-metadata:s:s', f'title={metadata["subtitle"]}',
        '-map', '0',
        '-c', 'copy',
        '-loglevel', 'error',
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()}")

def get_file_duration(file_path):
    """Get duration of media file"""
    try:
        metadata = extractMetadata(createParser(file_path))
        if metadata is not None and metadata.has("duration"):
            return str(datetime.timedelta(seconds=int(metadata.get("duration").seconds)))
        return "00:00:00"
    except Exception as e:
        logger.error(f"Error getting duration: {e}")
        return "00:00:00"

def format_caption(caption_template, filename, filesize, duration):
    """Replace caption variables with actual values"""
    if not caption_template:
        return None
    
    # Convert filesize to human-readable format
    filesize_str = humanbytes(filesize)
    
    # Perform replacements
    caption = caption_template
    caption = caption.replace("{filename}", filename)
    caption = caption.replace("{filesize}", filesize_str)
    caption = caption.replace("{duration}", duration)
    
    return caption
    
# --- The main processing function called by the queue ---
async def process_rename_task(
    client: Client,
    user_id: int,
    message_dict: Dict[str, Any], # Dictionary representation of the original message
    file_id: str,
    new_name: str,
    rename_source: str,
    original_message_id: int, # The ID of the message that initiated the rename
    processing_message_id: int # The ID of the message sent by the bot for "Processing..."
) -> Tuple[bool, str]:
    """
    Processes a single file renaming task. This function is called by the RenameQueue worker.
    """
    chat_id = message_dict["chat"]["id"]
    
    # Reconstruct essential media info from message_dict
    media = None
    media_type = None
    file_original_name = "unknown_file"
    file_size = 0

    if message_dict.get('document'):
        media = message_dict['document']
        media_type = "document"
        file_original_name = media.get('file_name', 'document_file')
        file_size = media.get('file_size', 0)
    elif message_dict.get('video'):
        media = message_dict['video']
        media_type = "video"
        file_original_name = media.get('file_name', 'video_file')
        file_size = media.get('file_size', 0)
    elif message_dict.get('audio'):
        media = message_dict['audio']
        media_type = "audio"
        file_original_name = media.get('file_name', 'audio_file')
        file_size = media.get('file_size', 0)
    else:
        logger.error(f"process_rename_task: No valid media found in message_dict for user {user_id}")
        return False, "Unsupported file type or missing media info."

    # Skip if user is in sequence mode
    if is_in_sequence_mode(user_id):
        logger.info(f"User {user_id} is in sequence mode, skipping rename in processor")
        return False, "User is in sequence mode. Cannot rename this file."

    # Initialize paths to None for proper cleanup handling
    download_path = None
    metadata_path = None
    thumb_path = None
    
    # Attempt to get or create the processing message to update progress
    msg = None
    try:
        msg = await client.get_messages(chat_id=chat_id, message_ids=processing_message_id)
        await msg.edit_text("⏳ Your file is now being processed...")
    except Exception:
        # If the original processing message is gone, send a new one
        msg = await client.send_message(chat_id=chat_id, text="⏳ Your file is now being processed...")

    if not msg: # If even sending a new message failed
        logger.error(f"Failed to obtain/send processing message for user {user_id}")
        return False, "Failed to send status updates."


    try:
        # Extract metadata from original file name (if needed for auto-naming based on template)
        # Note: 'new_name' is already the target name from filerenamer.py.
        # This section is for extracting season/episode/quality from the *original* file name
        # which might be used if 'new_name' is not fully specified or if user
        # relies on an 'autorename' template. Assuming `new_name` is final here.
        season, episode = extract_season_episode(file_original_name)
        quality = extract_quality(file_original_name)

        # Determine file extension
        ext = os.path.splitext(file_original_name)[1]
        if not ext and media_type == 'video':
            ext = '.mp4'
        elif not ext and media_type == 'audio':
            ext = '.mp3'
        elif not ext and media_type == 'document':
            mime_type = media.get('mime_type')
            if mime_type:
                ext = '.' + mime_type.split('/')[-1]
            else:
                ext = '.bin'

        final_filename = f"{new_name}{ext}" # Use the provided new_name + derived extension

        download_path = os.path.join("downloads", final_filename)
        metadata_path = os.path.join("metadata", final_filename) # Path where metadata-added file will be saved
        
        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        os.makedirs(os.path.dirname(metadata_path), exist_ok=True)

        # Download file
        await msg.edit_text("**Downloading...**")
        try:
            file_path = await client.download_media(
                file_id,
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", msg, time.time())
            )
        except Exception as e:
            await msg.edit_text(f"Download failed: {e}")
            raise

        # Process metadata
        await msg.edit_text("**Processing metadata...**")
        try:
            await add_metadata(file_path, metadata_path, user_id)
            file_path_for_upload = metadata_path # Use the file with metadata
        except RuntimeError as e: # Catch custom RuntimeError from add_metadata
            logger.warning(f"Metadata addition failed for user {user_id}, using original downloaded file: {e}")
            file_path_for_upload = download_path # Fallback to original downloaded file
            await msg.edit_text(f"Metadata processing failed: {e}. Attempting to upload original file.")
        except Exception as e:
            logger.error(f"An unexpected error occurred during metadata processing for user {user_id}: {e}", exc_info=True)
            return False, f"Metadata processing failed unexpectedly: {e}"


        # Get duration for video/audio files
        duration = "00:00:00"
        if media_type in ["video", "audio"]:
            duration = get_file_duration(file_path_for_upload)

        # Prepare for upload
        await msg.edit_text("**Preparing upload...**")
        
        # Get caption template and replace variables
        caption_template = await db.get_caption(user_id) # Use user_id directly
        if caption_template:
            caption = format_caption(caption_template, final_filename, file_size, duration)
        else:
            caption = f"**{final_filename}**"
            
        # Get user thumbnail preference or original video thumbnail from message_dict
        thumb_file_id = await db.get_thumbnail(user_id)
        
        if thumb_file_id:
            thumb_path = await client.download_media(thumb_file_id)
        elif media_type == "video" and media.get('thumbs'): # Check if video and has thumbs in message_dict
            thumb_path = await client.download_media(media['thumbs'][0]['file_id']) # Get largest thumb
            
        if thumb_path:
            thumb_path = await process_thumbnail(thumb_path)

        # Get user's preferred media type for sending (document/video/audio)
        user_media_preference = await db.get_media_preference(user_id)
        logger.info(f"User {user_id} media preference: {user_media_preference}")
        
        if not user_media_preference:
            user_media_preference = media_type
            logger.info(f"No preference set for user {user_id}, using original type: {media_type}")
        else:
            user_media_preference = user_media_preference.lower()
            logger.info(f"Using user's preference: {user_media_preference} for user {user_id}")

        # Upload file
        await msg.edit_text("**Uploading...**")
        try:
            upload_params = {
                'chat_id': chat_id,
                'caption': caption,
                'progress': progress_for_pyrogram,
                'progress_args': ("Uploading...", msg, time.time())
            }
            
            if thumb_path:
                upload_params['thumb'] = thumb_path

            # Use user's media preference for sending
            if user_media_preference == "document":
                await client.send_document(document=file_path_for_upload, **upload_params)
            elif user_media_preference == "video":
                # For send_video, need to extract width, height, duration
                upload_params['duration'] = media.get('duration') or get_file_duration(file_path_for_upload)
                upload_params['width'] = media.get('width')
                upload_params['height'] = media.get('height')
                await client.send_video(video=file_path_for_upload, **upload_params)
            elif user_media_preference == "audio":
                # For send_audio, need duration, title, performer
                upload_params['duration'] = media.get('duration') or get_file_duration(file_path_for_upload)
                upload_params['title'] = media.get('title')
                upload_params['performer'] = media.get('performer')
                await client.send_audio(audio=file_path_for_upload, **upload_params)
            else: # Fallback if preference is invalid
                logger.warning(f"Invalid preference: {user_media_preference} for user {user_id}, falling back to original media type: {media_type}")
                if media_type == "document":
                    await client.send_document(document=file_path_for_upload, **upload_params)
                elif media_type == "video":
                    upload_params['duration'] = media.get('duration') or get_file_duration(file_path_for_upload)
                    upload_params['width'] = media.get('width')
                    upload_params['height'] = media.get('height')
                    await client.send_video(video=file_path_for_upload, **upload_params)
                elif media_type == "audio":
                    upload_params['duration'] = media.get('duration') or get_file_duration(file_path_for_upload)
                    upload_params['title'] = media.get('title')
                    upload_params['performer'] = media.get('performer')
                    await client.send_audio(audio=file_path_for_upload, **upload_params)

            await msg.delete() # Delete the processing message
            return True, "File renamed and uploaded successfully!"

        except FloodWait as e:
            logger.warning(f"FloodWait for user {user_id}: {e.value} seconds")
            # Edit the processing message with FloodWait info
            await msg.edit_text(f"Telegram is asking me to wait for {e.value} seconds due to flood limits. Please try again after some time.")
            await asyncio.sleep(e.value) # Wait for the flood limit
            return False, f"Flood limit hit, please retry."
        except Exception as e:
            logger.error(f"Upload failed for user {user_id}: {e}", exc_info=True)
            if msg: # Ensure msg exists before attempting to edit
                await msg.edit_text(f"Upload failed: {e}")
            return False, f"Upload failed: {e}"

    except Exception as e:
        logger.error(f"Overall processing error for user {user_id}: {e}", exc_info=True)
        if msg: # Ensure msg exists before attempting to edit
            await msg.edit_text(f"Error during renaming: {str(e)}")
        return False, f"Error during renaming: {str(e)}"
    finally:
        # Clean up files - safe to pass None values
        await cleanup_files(download_path, metadata_path, thumb_path)
