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

# Semaphore for purge operations
purge_semaphore = asyncio.Semaphore(1)

# Category restriction setup
def get_allowed_category_ids():
    """Get all allowed category IDs from config sections.

    Returns a set of category IDs found in config sections that are numeric
    and have a nodes_file option (indicating they are valid category sections).
    """
    allowed_categories = set()
    all_sections = config.sections()

    for section in all_sections:
        try:
            # Try to convert to int to see if it's a category ID
            category_id = int(section)
            # Check if it has nodes_file (indicating it's a valid category section)
            if config.has_option(section, "nodes_file"):
                allowed_categories.add(category_id)
        except (ValueError, TypeError):
            # Not a numeric section, skip it
            continue

    return allowed_categories

# Get allowed category IDs from config
ALLOWED_CATEGORY_IDS = get_allowed_category_ids()

if ALLOWED_CATEGORY_IDS:
    logger.info(f"Category restriction enabled: commands will only work in repeater-control channels within category IDs {ALLOWED_CATEGORY_IDS}")
else:
    logger.info("No category sections found in config - commands will work in all channels")

# Category check hook
@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS, skip_when_failed=True)
async def category_check(pl: lightbulb.ExecutionPipeline, ctx: lightbulb.Context) -> None:
    """Check if command is being executed in the repeater-control channel of an allowed category"""
    # If no category restriction is set, allow all
    if not ALLOWED_CATEGORY_IDS:
        return

    try:
        # Get the channel where the command was invoked
        channel = await bot.rest.fetch_channel(ctx.channel_id)

        # Get the category ID (parent_id)
        category_id = channel.parent_id

        # If channel has no category, deny (unless category restriction is disabled)
        if not category_id:
            await ctx.respond(f"{CROSS} This command can only be used in a specific category.", flags=hikari.MessageFlag.EPHEMERAL)
            raise RuntimeError("Command executed outside allowed category")

        # Check if the category is in the allowed categories list
        if category_id not in ALLOWED_CATEGORY_IDS:
            await ctx.respond(f"{CROSS} This command can only be used in a regional category.", flags=hikari.MessageFlag.EPHEMERAL)
            raise RuntimeError("Command executed outside allowed category")

        # Get the messenger channel ID for this category from config
        category_section = str(category_id)
        messenger_channel_id = config.get(category_section, "messenger_channel_id", fallback=None)

        # If no messenger_channel_id is configured for this category, deny
        if not messenger_channel_id:
            await ctx.respond(f"{CROSS} This command can only be used in the repeater-control channel for this region.", flags=hikari.MessageFlag.EPHEMERAL)
            raise RuntimeError(f"No messenger channel configured for category {category_section}")

        # Convert to int for comparison
        try:
            messenger_channel_id = int(messenger_channel_id)
        except (ValueError, TypeError):
            await ctx.respond(f"{CROSS} Invalid repeater-control channel configuration for this region.", flags=hikari.MessageFlag.EPHEMERAL)
            raise RuntimeError(f"Invalid messenger channel ID in category {category_section}")

        # Check if the command is being executed in the messenger channel
        if ctx.channel_id != messenger_channel_id:
            await ctx.respond(f"{CROSS} This command can only be used in the repeater-control channel for this region.", flags=hikari.MessageFlag.EPHEMERAL)
            raise RuntimeError("Command executed outside messenger channel")
    except RuntimeError:
        # Re-raise RuntimeError to fail the pipeline
        raise
    except Exception as e:
        logger.error(f"Error checking category: {e}")
        raise RuntimeError("Error checking category") from e
