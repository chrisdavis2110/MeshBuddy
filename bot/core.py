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

# Command hooks
@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS, skip_when_failed=True)
async def channel_check(pl: lightbulb.ExecutionPipeline, ctx: lightbulb.Context) -> None:
    """Hook to check if command is invoked in a valid channel"""
    # Allow commands in any channel - channel-specific file mapping is handled in utils
    pass

# Legacy alias for backwards compatibility
category_check = channel_check