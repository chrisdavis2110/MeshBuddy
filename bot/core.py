"""
Bot Core Module

Contains bot initialization, configuration, and shared constants.
This is the foundation that other modules import from.
"""

import hikari
import lightbulb
import logging
import asyncio
from helpers import load_config

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Load configuration
config = load_config("config.ini")

# Initialize bot and client
bot = hikari.GatewayBot(config.get("discord", "token"))
client = lightbulb.client_from_app(bot)
bot.subscribe(hikari.StartingEvent, client.start)

# Constants
EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
CHECK = "✅"
CROSS = "❌"
WARN = "⚠️"
RESERVED = "⏳"

# Global state (shared across modules)
pending_remove_selections = {}
pending_qr_selections = {}
pending_own_selections = {}
pending_unclaim_selections = {}
pending_owner_selections = {}
known_node_keys = set()
purge_semaphore = asyncio.Semaphore(1)  # Ensure only one purge operation at a time

# Command hooks
@lightbulb.implements(lightbulb.SlashCommand)
async def channel_check(ctx: lightbulb.Context) -> bool:
    """Hook to check if command is invoked in a valid channel"""
    # Allow commands in any channel - channel-specific file mapping is handled in utils
    return True

# Legacy alias for backwards compatibility
category_check = channel_check