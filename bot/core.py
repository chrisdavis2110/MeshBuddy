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
    # Get allowed channel IDs from config
    bot_messenger_channel_id = config.get("discord", "bot_messenger_channel_id", fallback=None)

    # Build list of allowed channels
    allowed_channels = []
    if bot_messenger_channel_id:
        try:
            allowed_channels.append(int(bot_messenger_channel_id))
        except (ValueError, TypeError):
            pass

    # If no channels configured, allow all (backward compatibility)
    if not allowed_channels:
        logger.warning("No bot_messenger_channel_id configured - allowing commands in all channels")
        return

    # Check if command is in an allowed channel
    if ctx.channel_id not in allowed_channels:
        # Get channel names for better error message
        allowed_channel_names = []
        for channel_id in allowed_channels:
            try:
                channel = await bot.rest.fetch_channel(channel_id)
                channel_name = channel.name if hasattr(channel, 'name') else f"<#{channel_id}>"
                allowed_channel_names.append(f"#{channel_name}")
            except Exception as e:
                logger.debug(f"Could not fetch channel {channel_id}: {e}")
                allowed_channel_names.append(f"<#{channel_id}>")

        allowed_channels_str = ", ".join(allowed_channel_names) if allowed_channel_names else ", ".join(str(c) for c in allowed_channels)
        try:
            await ctx.respond(
                f"❌ This command can only be used in the bot messenger channel(s): {allowed_channels_str}",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error sending channel restriction message: {e}")
        # Prevent command execution by raising an exception
        # The hook has skip_when_failed=True, so any exception will prevent the command from running
        raise Exception("Command not allowed in this channel")

# Legacy alias for backwards compatibility
category_check = channel_check