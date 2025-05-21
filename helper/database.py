import motor.motor_asyncio
import datetime
import pytz
from config import Config
import logging
from .utils import send_log # Assuming this is correct for your setup

# Configure logging for the database module
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self, uri, database_name):
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
            self._client.server_info()  # This will raise an exception if the connection fails
            logging.info("Successfully connected to MongoDB")
        except Exception as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            raise e  # Re-raise the exception after logging it
        self.codeflixbots = self._client[database_name]
        self.col = self.codeflixbots.user

    def new_user(self, id):
        # Ensure 'daily_rename_count' and 'last_rename_reset' are initialized for new users
        return dict(
            _id=int(id),
            join_date=datetime.date.today().isoformat(),
            file_id=None,
            caption=None,
            metadata=True,
            metadata_code="Telegram : @Codeflix_Bots",
            format_template=None,
            premium=dict(
                is_premium=False,
                expiry_date=None,
                added_on=None,
                duration=None
            ),
            ban_status=dict(
                is_banned=False,
                ban_duration=0,
                banned_on=datetime.date.max.isoformat(),
                ban_reason=''
            ),
            daily_rename_count=0, # New: Initialize daily count
            last_rename_reset=datetime.datetime.now(pytz.utc).isoformat(), # New: Initialize last reset time
            daily_limit=None # New: Optional custom daily limit, None means use default
        )

    async def add_user(self, b, m):
        u = m.from_user
        if not await self.is_user_exist(u.id):
            user = self.new_user(u.id)
            try:
                await self.col.insert_one(user)
                await send_log(b, u)
            except Exception as e:
                logging.error(f"Error adding user {u.id}: {e}")

    async def is_user_exist(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return bool(user)
        except Exception as e:
            logging.error(f"Error checking if user {id} exists: {e}")
            return False

    async def total_users_count(self):
        try:
            count = await self.col.count_documents({})
            return count
        except Exception as e:
            logging.error(f"Error counting users: {e}")
            return 0

    async def get_all_users(self):
        try:
            all_users = self.col.find({})
            return all_users
        except Exception as e:
            logging.error(f"Error getting all users: {e}")
            return None

    async def delete_user(self, user_id):
        try:
            await self.col.delete_many({"_id": int(user_id)})
        except Exception as e:
            logging.error(f"Error deleting user {user_id}: {e}")

    async def set_thumbnail(self, id, file_id):
        try:
            await self.col.update_one({"_id": int(id)}, {"$set": {"file_id": file_id}})
        except Exception as e:
            logging.error(f"Error setting thumbnail for user {id}: {e}")

    async def get_thumbnail(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("file_id", None) if user else None
        except Exception as e:
            logging.error(f"Error getting thumbnail for user {id}: {e}")
            return None

    async def set_caption(self, id, caption):
        try:
            await self.col.update_one({"_id": int(id)}, {"$set": {"caption": caption}})
        except Exception as e:
            logging.error(f"Error setting caption for user {id}: {e}")

    async def get_caption(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("caption", None) if user else None
        except Exception as e:
            logging.error(f"Error getting caption for user {id}: {e}")
            return None

    async def set_format_template(self, id, format_template):
        try:
            await self.col.update_one(
                {"_id": int(id)}, {"$set": {"format_template": format_template}}
            )
        except Exception as e:
            logging.error(f"Error setting format template for user {id}: {e}")

    async def get_format_template(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("format_template", None) if user else None
        except Exception as e:
            logging.error(f"Error getting format template for user {id}: {e}")
            return None

    async def set_media_preference(self, id, media_type):
        try:
            await self.col.update_one(
                {"_id": int(id)}, {"$set": {"media_type": media_type}}
            )
        except Exception as e:
            logging.error(f"Error setting media preference for user {id}: {e}")

    async def get_media_preference(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("media_type", None) if user else None
        except Exception as e:
            logging.error(f"Error getting media preference for user {id}: {e}")
            return None

    async def get_metadata(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('metadata', "Off")

    async def set_metadata(self, user_id, metadata):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'metadata': metadata}})

    async def get_title(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('title', 'Encoded by @Animes_Station')

    async def set_title(self, user_id, title):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'title': title}})

    async def get_author(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('author', '@Animes_Station')

    async def set_author(self, user_id, author):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'author': author}})

    async def get_artist(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('artist', '@Animes_Station')

    async def set_artist(self, user_id, artist):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'artist': artist}})

    async def get_audio(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('audio', 'By @Animes_Station')

    async def set_audio(self, user_id, audio):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'audio': audio}})

    async def get_subtitle(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('subtitle', "By @Animes_Station")

    async def set_subtitle(self, user_id, subtitle):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'subtitle': subtitle}})

    async def get_video(self, user_id):
        user = await self.col.find_one({'_id': int(user_id)})
        return user.get('video', 'Encoded By @Animes_Station')

    async def set_video(self, user_id, video):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'video': video}})

    # --- Premium User Methods (Existing, ensure they use datetime.datetime.now(pytz.utc)) ---
    async def is_premium_user(self, id):
        """Check if a user is premium and their subscription hasn't expired"""
        try:
            user = await self.col.find_one({"_id": int(id)})
            if not user or "premium" not in user:
                return False
                
            if not user["premium"].get("is_premium", False):
                return False
                
            expiry = user["premium"].get("expiry_date")
            if not expiry:
                return False
                
            # Convert string to datetime and localize to UTC for comparison
            expiry_date = datetime.datetime.fromisoformat(expiry).replace(tzinfo=pytz.utc)
            current_date = datetime.datetime.now(pytz.utc)
            
            # Check if premium has expired
            if current_date > expiry_date:
                # Premium expired, update the status
                await self.col.update_one(
                    {"_id": int(id)},
                    {"$set": {"premium.is_premium": False}}
                )
                return False
                
            return True
        except Exception as e:
            logging.error(f"Error checking premium status for user {id}: {e}")
            return False
    
    async def add_premium_user(self, id, duration):
        """Add or update a user's premium status"""
        try:
            # Calculate expiry date
            current_date = datetime.datetime.now(pytz.utc)
            
            # Parse duration string (format: Xm/Xh/Xd/Xmh where X is a number)
            duration_value = int(duration[:-1] if duration[-2:] != "mh" else duration[:-2])
            duration_unit = duration[-1] if duration[-2:] != "mh" else "mh"
            
            if duration_unit == "m":
                expiry_date = current_date + datetime.timedelta(minutes=duration_value)
            elif duration_unit == "h":
                expiry_date = current_date + datetime.timedelta(hours=duration_value)
            elif duration_unit == "d":
                expiry_date = current_date + datetime.timedelta(days=duration_value)
            elif duration_unit == "mh":  # month
                # Add months (approximately)
                expiry_date = current_date + datetime.timedelta(days=30 * duration_value) # Using 30 days as an approximation for a month
            else:
                raise ValueError(f"Invalid duration format: {duration}")
            
            # Update user in database
            await self.col.update_one(
                {"_id": int(id)},
                {"$set": {
                    "premium": {
                        "is_premium": True,
                        "expiry_date": expiry_date.isoformat(),
                        "added_on": current_date.isoformat(),
                        "duration": duration
                    }
                }},
                upsert=True
            )
            return True, expiry_date.isoformat()
        except Exception as e:
            logging.error(f"Error adding premium user {id}: {e}")
            return False, str(e)
    
    async def get_premium_details(self, id):
        """Get premium details for a user"""
        try:
            user = await self.col.find_one({"_id": int(id)})
            if not user or "premium" not in user:
                return None
            
            return user["premium"]
        except Exception as e:
            logging.error(f"Error getting premium details for user {id}: {e}")
            return None
    
    async def remove_premium(self, id):
        """Remove premium status from a user"""
        try:
            await self.col.update_one(
                {"_id": int(id)},
                {"$set": {"premium.is_premium": False}}
            )
            return True
        except Exception as e:
            logging.error(f"Error removing premium from user {id}: {e}")
            return False

    # --- NEW METHODS FOR DAILY LIMITS (ADD THESE) ---

    async def get_daily_limit(self, user_id: int) -> int:
        """
        Gets the user's custom daily limit.
        If no custom limit is set, it returns Config.DEFAULT_DAILY_RENAME_LIMIT.
        """
        user = await self.col.find_one({"_id": user_id})
        # If 'daily_limit' is explicitly set to None, it also means use default.
        if user and user.get("daily_limit") is not None:
            return user["daily_limit"]
        return Config.DEFAULT_DAILY_RENAME_LIMIT # Use a default from Config

    async def set_daily_limit(self, user_id: int, limit: int):
        """
        Sets a custom daily renaming limit for a specific user.
        Set to -1 for unlimited for that specific user.
        """
        await self.col.update_one(
            {"_id": user_id},
            {"$set": {"daily_limit": limit}},
            upsert=True
        )
        logger.info(f"Set daily limit for user {user_id} to {limit}")

    async def get_daily_rename_count(self, user_id: int) -> tuple[int, int]:
        """
        Gets the user's current daily rename count and their specific limit.
        Resets the count to 0 if a new day has started since the last reset.
        Returns (current_count, limit_for_user).
        """
        user = await self.col.find_one({"_id": user_id})
        
        # Get current time in UTC to avoid timezone issues
        current_datetime_utc = datetime.datetime.now(pytz.utc)
        current_date_utc = current_datetime_utc.date()
        
        count = user.get("daily_rename_count", 0) if user else 0
        
        # Get last_rename_reset, default to current UTC datetime if not found
        last_reset_dt = datetime.datetime.fromisoformat(user.get("last_rename_reset", current_datetime_utc.isoformat())).replace(tzinfo=pytz.utc) if user else current_datetime_utc
        last_reset_date_utc = last_reset_dt.date()

        limit_for_user = await self.get_daily_limit(user_id) # Get their specific limit

        if last_reset_date_utc < current_date_utc:
            # A new day has started, reset the count
            count = 0
            await self.col.update_one(
                {"_id": user_id},
                {"$set": {"daily_rename_count": 0, "last_rename_reset": current_datetime_utc.isoformat()}},
                upsert=True
            )
            logger.info(f"Daily rename count reset for user {user_id}. New day.")
        
        return count, limit_for_user

    async def increment_daily_rename_count(self, user_id: int):
        """Increments the user's daily rename count."""
        # Ensure the count is reset if a new day started before incrementing
        # This call implicitly handles the daily reset logic
        await self.get_daily_rename_count(user_id)
        
        await self.col.update_one(
            {"_id": user_id},
            {"$inc": {"daily_rename_count": 1}},
            upsert=True
        )
        logger.info(f"Incremented daily rename count for user {user_id}")

# Initialize the Database class with your Config values
# This line is likely at the very end of your database.py
db = Database(Config.DB_URL, Config.DB_NAME)
