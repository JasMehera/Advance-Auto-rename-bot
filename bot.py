import os
import asyncio
import warnings
import time
from datetime import datetime, timedelta
from pytz import timezone
from pyrogram import Client, __version__, idle
from pyrogram.raw.all import layer
import pyrogram.utils
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyromod import listen # This is important for pyromod functions
from aiohttp import web # For webhook
from route import web_server # Assuming 'route.py' exists and defines web_server
from config import Config # Your Config file
from helper.database import db # Your database instance

# Suppress unclosed client session warnings from aiohttp
warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed client session")

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

# Setting SUPPORT_CHAT directly here (ensure this is an integer chat ID)
SUPPORT_CHAT = int(os.environ.get("SUPPORT_CHAT", "-1002607710343"))

PORT = Config.PORT # Get PORT from Config

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="codeflixbots", # The name of your bot session
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=200,
            plugins={"root": "plugins"},
            sleep_threshold=15,
        )
        # Initialize the bot's start time for uptime calculation
        self.start_time = time.time()
        # Initialize aiohttp session for potential HTTP requests later if needed
        self.aiohttp_session = None 
    
    async def start(self):
        # This is called automatically by Pyrogram's .run()
        await super().start() # Calls the parent (Client) start method
        
        # Connect to MongoDB
        await db.connect()
        print("Connected to MongoDB!")

        # Initialize aiohttp session if not already done
        if not self.aiohttp_session:
            self.aiohttp_session = aiohttp.ClientSession()

        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username  
        
        # Start Webhook if enabled
        if Config.WEBHOOK:
            app = web.AppRunner(await web_server())
            await app.setup()       
            await web.TCPSite(app, "0.0.0.0", PORT).start()
            print(f"Webhook server started on port {PORT}") # Confirmation message
        
        print(f"{me.first_name} Is Started.....✨️")

        # Calculate uptime using timedelta
        uptime_seconds = int(time.time() - self.start_time)
        uptime_string = str(timedelta(seconds=uptime_seconds))

        for chat_id in [Config.LOG_CHANNEL, SUPPORT_CHAT]:
            try:
                curr = datetime.now(timezone("Asia/Kolkata"))
                date = curr.strftime('%d %B, %Y')
                time_str = curr.strftime('%I:%M:%S %p')
                
                # Send the message with the photo
                await self.send_photo(
                    chat_id=chat_id,
                    photo=Config.START_PIC,
                    caption=(
                        "**Dᴀɴᴛᴇ ɪs ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ  !**\n\n"
                        f"ɪ ᴅɪᴅɴ'ᴛ sʟᴇᴘᴛ sɪɴᴄᴇ​: `{uptime_string}`"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/weebs_union")
                        ]]
                    )
                )

            except Exception as e:
                print(f"Failed to send startup message in chat {chat_id}: {e}")
        
        # Keep the bot running indefinitely, listening for updates
        await idle()

    async def stop(self, *args):
        # This is called automatically by Pyrogram's .run() on shutdown
        await super().stop() # Calls the parent (Client) stop method
        
        if self.aiohttp_session:
            await self.aiohttp_session.close() # Close aiohttp session
            print("aiohttp session closed.")
            
        await db.close() # Close database connection
        print("Bot stopped and disconnected from MongoDB.")


if __name__ == "__main__":
    # The .run() method of Pyrogram Client handles the entire event loop.
    # We simply instantiate the bot and call run().
    print("Attempting to start bot...")
    Bot().run()
    print("Bot process finished.")
