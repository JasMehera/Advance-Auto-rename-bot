import asyncio
from collections import deque
from typing import Dict, Any, Tuple
from pyrogram import Client
from helper.database import codeflixbots # Make sure 'codeflixbots' is imported correctly for your DB
from datetime import datetime
import logging
from bot.rename_processor import process_rename_task # Import the renamed processor

# Configure logging for the queue module
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RenameQueue:
    _instance = None
    _queue: deque = deque()
    _processing_lock = asyncio.Lock()
    _processing_task: asyncio.Task = None

    def __new__(cls):
        """Singleton pattern to ensure only one instance of RenameQueue."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._queue = deque()
            cls._instance._processing_lock = asyncio.Lock()
            cls._instance._processing_task = None
        return cls._instance

    @staticmethod
    def get_instance():
        """Returns the singleton instance of RenameQueue."""
        return RenameQueue()

    async def add_to_queue(self, user_id: int, message_dict: Dict[str, Any], file_id: str, new_name: str, rename_source: str) -> Tuple[bool, str]:
        """
        Adds a renaming task to the queue.
        `message_dict` should be a dictionary representation of the original message
        to avoid passing a Pyrogram Message object directly, which can cause issues
        if the object becomes stale.
        `rename_source`: 'caption' or 'filename'
        """
        is_premium = await codeflixbots.is_premium_user(user_id)
        
        task_info = {
            "user_id": user_id,
            "message_id": message_dict["id"],
            "chat_id": message_dict["chat"]["id"],
            "file_id": file_id,
            "new_name": new_name,
            "rename_source": rename_source, # Store the rename source preference
            "is_premium": is_premium,
            "added_at": datetime.now(),
            "status": "pending"
        }

        # You can add rate limiting or queue size limits here if needed
        # current_user_tasks = sum(1 for task in self._queue if task["user_id"] == user_id)
        # if not is_premium and current_user_tasks >= Config.MAX_NON_PREMIUM_QUEUE_TASKS: # Define this in config.py
        #    return False, "You have too many files in the queue. Please wait for previous tasks to complete or upgrade to premium."

        async with self._processing_lock: # Ensure thread-safety for queue modification
            if is_premium:
                self._queue.appendleft(task_info) # Premium users get priority
                status_msg = "✅ File added to **premium queue**! Processing will begin shortly."
            else:
                self._queue.append(task_info) # Non-premium users are appended to the end
                status_msg = "✅ File added to queue! Please wait for your turn."

        logger.info(f"Task added to queue for user {user_id}. Premium: {is_premium}. Current queue size: {len(self._queue)}")
        return True, status_msg

    async def _worker(self, client: Client):
        """Worker function that continuously processes renaming tasks from the queue."""
        while True:
            try:
                task = None
                async with self._processing_lock:
                    if self._queue:
                        task = self._queue.popleft() # Get task from the front

                if task:
                    user_id = task["user_id"]
                    message_id = task["message_id"]
                    chat_id = task["chat_id"]
                    file_id = task["file_id"]
                    new_name = task["new_name"]
                    rename_source = task["rename_source"] # Retrieve rename source
                    
                    logger.info(f"Worker: Processing task for user {user_id}, message {message_id}")
                    
                    processing_message = None # Initialize to None
                    try:
                        # Notify user that processing has started
                        processing_message = await client.send_message(
                            chat_id=chat_id,
                            text="⏳ Your file is now being processed..."
                        )

                        # Call the core renaming logic
                        success, result_message = await process_rename_task(
                            client, 
                            user_id, 
                            file_id, 
                            new_name, 
                            rename_source, # Pass rename_source to processor
                            original_message_id=message_id, 
                            processing_message_id=processing_message.id 
                        )

                        if success:
                            logger.info(f"Worker: Task completed successfully for user {user_id}")
                            # Result message (e.g., the renamed file) is handled by process_rename_task
                            # No need to send another message here unless you want a final "Done!"
                            # If process_rename_task edits the processing_message, that's enough.
                        else:
                            logger.error(f"Worker: Task failed for user {user_id}: {result_message}")
                            if processing_message:
                                await client.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=processing_message.id,
                                    text=f"❌ Renaming failed for your file: {result_message}"
                                )
                            else: # Fallback if processing_message couldn't be sent/edited
                                await client.send_message(
                                    chat_id=chat_id,
                                    text=f"❌ Renaming failed for your file: {result_message}"
                                )

                    except Exception as e:
                        logger.error(f"Worker: Error during file processing for user {user_id}: {e}", exc_info=True)
                        if processing_message:
                            try:
                                await client.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=processing_message.id,
                                    text=f"❌ An unexpected error occurred during processing: {e}"
                                )
                            except Exception as edit_e:
                                logger.error(f"Worker: Failed to edit message after error: {edit_e}")
                                await client.send_message(
                                    chat_id=chat_id,
                                    text=f"❌ An unexpected error occurred during processing: {e}"
                                )
                        else:
                            await client.send_message(
                                chat_id=chat_id,
                                text=f"❌ An unexpected error occurred during processing: {e}"
                            )
                    finally:
                        await asyncio.sleep(2) # Small delay to prevent API flooding between tasks
                else:
                    await asyncio.sleep(5) # Wait if queue is empty

            except Exception as e:
                logger.error(f"Worker: Unhandled error in queue worker loop: {e}", exc_info=True)
                await asyncio.sleep(10) # Longer sleep on unhandled worker error

    def start_worker(self, client: Client):
        """Starts the queue processing worker as an asyncio task."""
        if self._processing_task is None or self._processing_task.done():
            self._processing_task = asyncio.create_task(self._worker(client))
            logger.info("Rename queue worker started.")
        else:
            logger.info("Rename queue worker already running.")

    def stop_worker(self):
        """Stops the queue processing worker."""
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            logger.info("Rename queue worker stopped.")

    def get_queue_status(self) -> str:
        """Returns the current status of the queue."""
        return f"Current queue size: {len(self._queue)} tasks."

    async def get_user_queue_position(self, user_id: int) -> Tuple[int, int]:
        """
        Gets a user's position in the queue and the total queue size.
        Returns (position, total_size). Position is 0-indexed.
        """
        async with self._processing_lock:
            total_size = len(self._queue)
            for i, task in enumerate(self._queue):
                if task["user_id"] == user_id:
                    return i + 1, total_size # Return 1-indexed position
            return 0, total_size # Not in queue
