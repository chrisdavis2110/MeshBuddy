#!/usr/bin/python

import hikari
import lightbulb
import logging
import asyncio
import json
import os
import time
import io
import urllib.parse
from datetime import datetime, timedelta
import qrcode
from concurrent.futures import ThreadPoolExecutor
from helpers import extract_device_types, load_config, load_data_from_json, get_unused_keys, get_repeater

# Initialize logging (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

config = load_config("config.ini")

bot = hikari.GatewayBot(config.get("discord", "token"))
client = lightbulb.client_from_app(bot)
bot.subscribe(hikari.StartingEvent, client.start)

EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
CHECK = "✅"
CROSS = "❌"
WARN = "⚠️"
RESERVED = "⏳"
pending_remove_selections = {}
pending_qr_selections = {}  # Track pending QR code selections
pending_own_selections = {}  # Track pending own/claim selections
pending_owner_selections = {} # Track pending owner lookup selections
known_node_keys = set()  # Track known node public_keys
# Semaphore to limit concurrent purge operations (only allow 1 at a time)
purge_semaphore = asyncio.Semaphore(1)

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


async def get_category_id_from_context(ctx: lightbulb.Context) -> int | None:
    """Get the category ID from the context where the command was invoked"""
    try:
        channel = await bot.rest.fetch_channel(ctx.channel_id)
        return channel.parent_id
    except Exception as e:
        logger.error(f"Error getting category ID from context: {e}")
        return None

def get_nodes_file_for_category(category_id: int | None) -> str:
    """Get the nodes file name based on category ID.

    Maps category IDs to node file names. If category_id is None or not found,
    defaults to 'nodes.json'.

    You can configure category-to-file mapping in config.ini using sections:
    [1442638798985891940]
    nodes_file = nodes_socal.json
    """
    if category_id is None:
        return "nodes.json"

    # Try to get category-specific node file from config section [category_id]
    category_section = str(category_id)
    nodes_file = config.get(category_section, "nodes_file", fallback=None)

    if nodes_file:
        logger.debug(f"Using category-specific nodes file: {nodes_file} for category {category_id}")
        return nodes_file

    # Default to nodes.json if no mapping found
    logger.debug(f"No category-specific nodes file found for category {category_id}, using default nodes.json")
    return "nodes.json"

def get_reserved_nodes_file_for_category(category_id: int | None) -> str:
    """Get the reserved nodes file name based on category ID.

    Maps category IDs to reserved nodes file names. If category_id is None or not found,
    defaults to 'reservedNodes.json'.

    You can configure category-to-file mapping in config.ini using sections:
    [1442638798985891940]
    reserved_nodes_file = reservedNodes_socal.json
    """
    if category_id is None:
        return "reservedNodes.json"

    # Try to get category-specific reserved nodes file from config section [category_id]
    category_section = str(category_id)
    reserved_file = config.get(category_section, "reserved_nodes_file", fallback=None)

    if reserved_file:
        logger.debug(f"Using category-specific reserved nodes file: {reserved_file} for category {category_id}")
        return reserved_file

    # Default to reservedNodes.json if no mapping found
    logger.debug(f"No category-specific reserved nodes file found for category {category_id}, using default reservedNodes.json")
    return "reservedNodes.json"

def get_removed_nodes_file_for_category(category_id: int | None) -> str:
    """Get the removed nodes file name based on category ID.

    Maps category IDs to removed nodes file names. If category_id is None or not found,
    defaults to 'removedNodes.json'.

    You can configure category-to-file mapping in config.ini using sections:
    [1442638798985891940]
    removed_nodes_file = removedNodes_socal.json
    """
    if category_id is None:
        return "removedNodes.json"

    # Try to get category-specific removed nodes file from config section [category_id]
    category_section = str(category_id)
    removed_file = config.get(category_section, "removed_nodes_file", fallback=None)

    if removed_file:
        logger.debug(f"Using category-specific removed nodes file: {removed_file} for category {category_id}")
        return removed_file

    # Default to removedNodes.json if no mapping found
    logger.debug(f"No category-specific removed nodes file found for category {category_id}, using default removedNodes.json")
    return "removedNodes.json"

async def get_reserved_nodes_file_for_context(ctx: lightbulb.Context) -> str:
    """Get reserved nodes file name based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    return get_reserved_nodes_file_for_category(category_id)

async def get_removed_nodes_file_for_context(ctx: lightbulb.Context) -> str:
    """Get removed nodes file name based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    return get_removed_nodes_file_for_category(category_id)

def get_owner_file_for_category(category_id: int | None) -> str:
    """Get the owner file name based on category ID.

    Maps category IDs to owner file names. If category_id is None or not found,
    defaults to 'repeaterOwners.json'.

    You can configure category-to-file mapping in config.ini using sections:
    [1442638798985891940]
    owners_file = repeaterOwners_socal.json
    """
    if category_id is None:
        return "repeaterOwners.json"

    # Try to get category-specific owner file from config section [category_id]
    category_section = str(category_id)
    owner_file = config.get(category_section, "owners_file", fallback=None)

    if owner_file:
        logger.debug(f"Using category-specific owner file: {owner_file} for category {category_id}")
        return owner_file

    # Default to repeaterOwners.json if no mapping found
    logger.debug(f"No category-specific owner file found for category {category_id}, using default repeaterOwners.json")
    return "repeaterOwners.json"

async def get_owner_file_for_context(ctx: lightbulb.Context) -> str:
    """Get owner file name based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    return get_owner_file_for_category(category_id)

async def get_nodes_data_for_context(ctx: lightbulb.Context):
    """Get nodes data based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    nodes_file = get_nodes_file_for_category(category_id)
    return load_data_from_json(nodes_file)

async def get_repeater_for_context(ctx: lightbulb.Context, prefix: str, days: int = 14):
    """Get repeater data based on the category where the command was invoked"""
    data = await get_nodes_data_for_context(ctx)
    # Use extract_device_types with the category-specific data
    from helpers.device_utils import extract_device_types
    devices = extract_device_types(data=data, device_types=['repeaters'], days=days)
    if devices is None:
        return None
    repeaters = devices.get('repeaters', [])
    # Find all repeaters with the specified prefix
    matching_repeaters = []
    for contact in repeaters:
        contact_prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
        if contact_prefix.upper() == prefix.upper():
            matching_repeaters.append(contact)
    return matching_repeaters if matching_repeaters else None

async def get_extract_device_types_for_context(ctx: lightbulb.Context, device_types=None, days=14):
    """Extract device types based on the category where the command was invoked"""
    data = await get_nodes_data_for_context(ctx)
    from helpers.device_utils import extract_device_types
    return extract_device_types(data=data, device_types=device_types, days=days)

async def get_unused_keys_for_context(ctx: lightbulb.Context, days=14):
    """Get unused keys based on the category where the command was invoked"""
    data = await get_nodes_data_for_context(ctx)
    from helpers.device_utils import extract_device_types
    devices = extract_device_types(data=data, device_types=['repeaters'], days=days)
    if devices is None:
        return None
    repeaters = devices.get('repeaters', [])
    # Load removed nodes to exclude them (category-specific)
    import os
    removed_set = set()
    category_id = await get_category_id_from_context(ctx)
    removed_nodes_file = get_removed_nodes_file_for_category(category_id)
    if os.path.exists(removed_nodes_file):
        try:
            with open(removed_nodes_file, 'r') as f:
                removed_data = json.load(f)
                for node in removed_data.get('data', []):
                    node_prefix = node.get('public_key', '').upper() if node.get('public_key') else ''
                    node_name = node.get('name', '').strip()
                    if node_prefix and node_name:
                        removed_set.add((node_prefix, node_name))
        except Exception:
            pass
    # Get all currently used prefixes (excluding removed nodes)
    used_keys = set()
    for contact in repeaters:
        contact_prefix = contact.get('public_key', '').upper() if contact.get('public_key') else ''
        contact_name = contact.get('name', '').strip()
        if (contact_prefix, contact_name) in removed_set:
            continue
        used_keys.add(contact_prefix[:2].upper())
    # Load reserved nodes (category-specific)
    reserved_set = set()
    reserved_nodes_file = get_reserved_nodes_file_for_category(category_id)
    if os.path.exists(reserved_nodes_file):
        try:
            with open(reserved_nodes_file, 'r') as f:
                reserved_data = json.load(f)
                for node in reserved_data.get('data', []):
                    prefix = node.get('prefix', '').upper()
                    if prefix:
                        reserved_set.add(prefix)
        except Exception as e:
            logger.debug(f"Error reading reservedNodes.json: {e}")
    # Generate all possible hex keys from 00 to FF
    all_possible_keys = set()
    for i in range(256):
        hex_key = f"{i:02X}"
        all_possible_keys.add(hex_key)
    # Find unused keys
    unused_keys = all_possible_keys - used_keys - reserved_set - set(['00', 'FF'])
    if unused_keys:
        return sorted(unused_keys)
    return []

# Cache for server emojis
server_emojis_cache = {}
emoji_name_to_string = {}  # Cache for formatted emoji strings

async def initialize_emojis(channel_id: int = None):
    """Pre-load emojis when bot starts"""
    global server_emojis_cache, emoji_name_to_string

    try:
        # Get channel ID from config if not provided
        if channel_id is None:
            channel_id = config.get("discord", "messenger_channel_id", fallback=None)

        if not channel_id:
            logger.warning("No channel_id available to initialize emojis")
            return

        channel_id_int = int(channel_id)
        channel = await bot.rest.fetch_channel(channel_id_int)
        guild_id = channel.guild_id

        if not guild_id:
            logger.warning(f"Channel {channel_id_int} has no guild_id")
            return

        # Fetch all emojis for the guild
        try:
            emojis = await bot.rest.fetch_guild_emojis(guild_id)
            server_emojis_cache[guild_id] = {emoji.name: emoji for emoji in emojis}

            # Log all available emoji names for debugging
            all_emoji_names = list(server_emojis_cache[guild_id].keys())
            logger.info(f"Available emojis in server ({len(all_emoji_names)} total): {', '.join(all_emoji_names[:50])}")
            if len(all_emoji_names) > 50:
                logger.info(f"... and {len(all_emoji_names) - 50} more")

            # Pre-format emoji strings for known emojis
            emoji_names = ["meshBuddy_new", "meshBuddy_salute", "WCMESH"]
            for name in emoji_names:
                # Try exact match first
                emoji = server_emojis_cache[guild_id].get(name)
                # Try case-insensitive match if exact match fails
                if not emoji:
                    for emoji_name, emoji_obj in server_emojis_cache[guild_id].items():
                        if emoji_name.lower() == name.lower():
                            emoji = emoji_obj
                            logger.info(f"Found emoji '{name}' as '{emoji_name}' (case-insensitive match)")
                            break

                if emoji:
                    # Use proper Discord format: <:name:id> or <a:name:id> for animated
                    if emoji.is_animated:
                        emoji_name_to_string[name] = f"<a:{emoji.name}:{emoji.id}>"
                    else:
                        emoji_name_to_string[name] = f"<:{emoji.name}:{emoji.id}>"
                    logger.info(f"Initialized emoji: {name} -> {emoji_name_to_string[name]}")
                else:
                    logger.warning(f"Emoji '{name}' not found during initialization. Searching emojis with similar names...")
                    # Try to find similar names
                    for emoji_name in all_emoji_names:
                        if 'mesh' in emoji_name.lower() or 'buddy' in emoji_name.lower() or 'new' in emoji_name.lower() or 'salute' in emoji_name.lower() or 'wcmesh' in emoji_name.lower():
                            logger.info(f"  Found similar emoji: '{emoji_name}'")

            logger.info(f"Initialized {len(emojis)} emojis for guild {guild_id}")
        except Exception as e:
            logger.error(f"Error initializing emojis: {e}")
    except Exception as e:
        logger.error(f"Error in initialize_emojis: {e}")

async def get_server_emoji(channel_id: int, emoji_name: str) -> str:
    """Get a Discord server emoji by name, with caching"""
    global server_emojis_cache, emoji_name_to_string

    # Check pre-initialized cache first
    if emoji_name in emoji_name_to_string:
        return emoji_name_to_string[emoji_name]

    # Check config for manual emoji ID override
    config_key = f"emoji_{emoji_name.lower()}_id"
    emoji_id = config.get("discord", config_key, fallback=None)
    if emoji_id:
        # Assume non-animated, can add animated flag to config if needed
        return f"<:{emoji_name}:{emoji_id}>"

    try:
        channel_id_int = int(channel_id)

        # Try to get guild_id from channel (via REST API)
        try:
            channel = await bot.rest.fetch_channel(channel_id_int)
            guild_id = channel.guild_id

            if not guild_id:
                logger.warning(f"Channel {channel_id_int} has no guild_id (might be DM)")
                return f":{emoji_name}:"

            # If not in cache, try REST API
            if guild_id not in server_emojis_cache:
                try:
                    emojis = await bot.rest.fetch_guild_emojis(guild_id)
                    server_emojis_cache[guild_id] = {emoji.name: emoji for emoji in emojis}
                    logger.info(f"Fetched and cached {len(emojis)} emojis for guild {guild_id}")

                    # Cache the formatted string for this emoji
                    emoji = server_emojis_cache[guild_id].get(emoji_name)
                    # Try case-insensitive match if exact match fails
                    if not emoji:
                        for name, emoji_obj in server_emojis_cache[guild_id].items():
                            if name.lower() == emoji_name.lower():
                                emoji = emoji_obj
                                break

                    if emoji:
                        if emoji.is_animated:
                            emoji_name_to_string[emoji_name] = f"<a:{emoji.name}:{emoji.id}>"
                        else:
                            emoji_name_to_string[emoji_name] = f"<:{emoji.name}:{emoji.id}>"
                        return emoji_name_to_string[emoji_name]
                except Exception as e:
                    logger.error(f"Error fetching emojis from REST API: {e}")
                    return f":{emoji_name}:"
            else:
                # Find emoji by name in our cache
                emoji = server_emojis_cache[guild_id].get(emoji_name)
                # Try case-insensitive match if exact match fails
                if not emoji:
                    for name, emoji_obj in server_emojis_cache[guild_id].items():
                        if name.lower() == emoji_name.lower():
                            emoji = emoji_obj
                            break

                if emoji:
                    # Cache the formatted string
                    if emoji.is_animated:
                        emoji_name_to_string[emoji_name] = f"<a:{emoji.name}:{emoji.id}>"
                    else:
                        emoji_name_to_string[emoji_name] = f"<:{emoji.name}:{emoji.id}>"
                    return emoji_name_to_string[emoji_name]

            # Emoji not found - log available ones for debugging
            if guild_id in server_emojis_cache:
                available_names = list(server_emojis_cache[guild_id].keys())
                logger.warning(f"Emoji '{emoji_name}' not found. Available emojis: {', '.join(available_names[:20])}")

            return f":{emoji_name}:"

        except Exception as e:
            logger.error(f"Error getting channel/guild: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return f":{emoji_name}:"

    except Exception as e:
        logger.error(f"Error getting server emoji '{emoji_name}': {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return f":{emoji_name}:"

def normalize_node(node):
    """Normalize node field names: handle both 'role'/'device_role' and 'last_heard'/'last_seen'"""
    if isinstance(node, dict):
        if 'role' in node and 'device_role' not in node:
            node['device_role'] = node['role']
        if 'last_heard' in node and 'last_seen' not in node:
            node['last_seen'] = node['last_heard']
    return node

def get_removed_nodes_set(removed_nodes_file="removedNodes.json"):
    """Load removedNodes.json and return a set of (prefix, name) tuples for quick lookup"""
    removed_set = set()

    if not os.path.exists(removed_nodes_file):
        return removed_set

    # Retry logic to handle race conditions when file is being written
    max_retries = 3
    retry_delay = 0.1  # seconds (shorter delay for synchronous function)

    for attempt in range(max_retries):
        try:
            # Check if file is empty before trying to parse
            if os.path.getsize(removed_nodes_file) == 0:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    return removed_set

            with open(removed_nodes_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        return removed_set

                # Parse JSON from content string
                removed_data = json.loads(content)
                for node in removed_data.get('data', []):
                    node_prefix = node.get('public_key', '').upper() if node.get('public_key') else ''
                    node_name = node.get('name', '').strip()
                    if node_prefix and node_name:
                        removed_set.add((node_prefix, node_name))
                return removed_set  # Success

        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                logger.debug(f"Error reading removedNodes.json: {e}")
                return removed_set
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                logger.debug(f"Error reading removedNodes.json: {e}")
                return removed_set

    return removed_set

def is_node_removed(contact, removed_nodes_file="removedNodes.json"):
    """Check if a contact node has been removed (uses default removedNodes.json)"""
    removed_set = get_removed_nodes_set(removed_nodes_file)
    prefix = contact.get('public_key', '').upper() if contact.get('public_key') else ''
    name = contact.get('name', '').strip()
    return (prefix, name) in removed_set

def is_node_removed_in_file(contact, removed_nodes_file):
    """Check if a contact node has been removed in a specific file"""
    removed_set = get_removed_nodes_set(removed_nodes_file)
    prefix = contact.get('public_key', '').upper() if contact.get('public_key') else ''
    name = contact.get('name', '').strip()
    return (prefix, name) in removed_set

async def generate_and_send_qr(contact, ctx_or_interaction):
    """Generate QR code for a contact and send it"""
    try:
        name = contact.get('name', 'Unknown')
        public_key = contact.get('public_key', '')
        device_role = contact.get('device_role', 2)

        if not public_key:
            error_msg = f"{CROSS} Error: Contact has no public key"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_msg,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(error_msg, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # URL encode the parameters
        encoded_name = urllib.parse.quote(name)
        encoded_public_key = urllib.parse.quote(public_key)

        # Build the meshcore:// URL
        qr_url = f"meshcore://contact/add?name={encoded_name}&public_key={encoded_public_key}&type={device_role}"

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        img_data = img_bytes.getvalue()

        # Send as file attachment
        prefix = public_key[:2].upper() if public_key else '??'
        message = f"QR Code for {prefix}: {name}"

        # Create file attachment using hikari.Bytes
        filename = f"qr_{prefix}_{name.replace(' ', '_')}.png"
        file_obj = hikari.Bytes(img_data, filename)

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                attachments=[file_obj],
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(
                message,
                attachments=[file_obj],
                flags=hikari.MessageFlag.EPHEMERAL
            )
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        error_message = f"{CROSS} Error generating QR code: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)

async def assign_repeater_owner_role(user_id: int, guild_id: int | None, category_id: int | None = None):
    """Assign repeater owner roles to a user when they claim a repeater (both global and category-specific)"""
    try:
        if not user_id or not guild_id:
            return False

        # Collect all roles to assign
        roles_to_assign = []

        # Add global repeater role if configured
        global_role_id_str = config.get("discord", "repeater_owner_role_id", fallback=None)
        if global_role_id_str:
            try:
                global_role_id = int(global_role_id_str)
                roles_to_assign.append(global_role_id)
            except (ValueError, TypeError):
                pass

        # Add category-specific repeater role if configured
        if category_id:
            category_section = str(category_id)
            category_role_id_str = config.get(category_section, "repeater_owner_role_id", fallback=None)
            if category_role_id_str:
                try:
                    category_role_id = int(category_role_id_str)
                    if category_role_id not in roles_to_assign:
                        roles_to_assign.append(category_role_id)
                except (ValueError, TypeError):
                    pass

        if not roles_to_assign:
            logger.debug("No repeater_owner_role_id configured, skipping role assignment")
            return False

        # Check if user already has all roles
        try:
            member = await bot.rest.fetch_member(guild_id, user_id)
            missing_roles = [rid for rid in roles_to_assign if rid not in member.role_ids]
            if not missing_roles:
                logger.debug(f"User {user_id} already has all repeater roles")
                return True
        except Exception as e:
            logger.debug(f"Error checking existing roles: {e}")
            missing_roles = roles_to_assign  # Assign all if we can't check

        # Assign all missing roles
        assigned_count = 0
        for role_id in missing_roles:
            try:
                await bot.rest.add_role_to_member(guild_id, user_id, role_id)
                logger.info(f"Assigned role {role_id} to user {user_id} in guild {guild_id}")
                assigned_count += 1
            except hikari.ForbiddenError:
                logger.warning(f"Bot doesn't have permission to assign role {role_id} in guild {guild_id}")
            except Exception as e:
                logger.error(f"Error assigning role {role_id} to user {user_id}: {e}")

        return assigned_count > 0
    except hikari.NotFoundError as e:
        logger.warning(f"Role or user not found in guild {guild_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error assigning repeater owner roles: {e}")
        return False

async def get_owner_info_for_repeater(repeater, owner_file: str):
    """Get owner information for a repeater from the owner file"""
    try:
        public_key = repeater.get('public_key', '')
        if not public_key:
            return None

        if not os.path.exists(owner_file):
            return None

        with open(owner_file, 'r') as f:
            content = f.read().strip()
            if not content:
                return None
            owners_data = json.loads(content)

        # Find owner by public_key
        for owner in owners_data.get('data', []):
            if owner.get('public_key', '').upper() == public_key.upper():
                return owner

        return None
    except Exception as e:
        logger.debug(f"Error getting owner info: {e}")
        return None

async def can_user_remove_repeater(repeater, user_id: int, ctx_or_interaction) -> tuple[bool, str]:
    """
    Check if a user can remove a repeater.

    Args:
        repeater: The repeater node to check
        user_id: The Discord user ID of the person trying to remove
        ctx_or_interaction: Context or interaction object for getting category info

    Returns:
        Tuple of (can_remove: bool, reason: str)
    """
    try:
        # Get bot owner ID from config
        bot_owner_id = None
        try:
            owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
            if owner_id_str:
                bot_owner_id = int(owner_id_str)
        except (ValueError, TypeError):
            pass

        # Check if user is the bot owner
        if bot_owner_id and user_id == bot_owner_id:
            return (True, "bot_owner")

        # Get owner file to check ownership
        if isinstance(ctx_or_interaction, lightbulb.Context):
            owner_file = await get_owner_file_for_context(ctx_or_interaction)
        elif hasattr(ctx_or_interaction, 'channel_id'):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                category_id = channel.parent_id
                owner_file = get_owner_file_for_category(category_id)
            except Exception:
                owner_file = "repeaterOwners.json"  # Fallback to default
        else:
            owner_file = "repeaterOwners.json"  # Fallback to default

        # Get owner info for this repeater
        owner_info = await get_owner_info_for_repeater(repeater, owner_file)

        if not owner_info:
            # No owner set, allow removal (unclaimed repeater)
            return (True, "no_owner")

        # Check if user is the owner
        owner_user_id = owner_info.get('user_id')
        if owner_user_id and int(owner_user_id) == user_id:
            return (True, "owner")

        # User is not the owner
        owner_display_name = owner_info.get('display_name') or owner_info.get('username', 'Unknown')
        return (False, f"Only the owner ({owner_display_name}) or bot owner can remove this repeater")

    except Exception as e:
        logger.error(f"Error checking if user can remove repeater: {e}")
        # On error, allow removal (fail open for safety)
        return (True, "error_check")

async def process_repeater_ownership(selected_repeater, ctx_or_interaction):
    """Process the ownership claim of a repeater and add to repeaterOwners.json (category-specific)"""
    try:
        # Get category-specific owner file
        if isinstance(ctx_or_interaction, lightbulb.Context):
            owner_file = await get_owner_file_for_context(ctx_or_interaction)
            username = ctx_or_interaction.user.username if ctx_or_interaction.user else "Unknown"
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            # For ComponentInteraction, we need to get category and user info
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                category_id = channel.parent_id
                owner_file = get_owner_file_for_category(category_id)
                username = ctx_or_interaction.user.username if ctx_or_interaction.user else "Unknown"
                user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
            except Exception:
                owner_file = "repeaterOwners.json"  # Fallback to default
                username = ctx_or_interaction.user.username if ctx_or_interaction.user else "Unknown"
                user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        else:
            owner_file = "repeaterOwners.json"  # Fallback to default
            username = "Unknown"
            user_id = None

        # Get display name (nickname if available)
        if isinstance(ctx_or_interaction, lightbulb.Context):
            display_name = await get_user_display_name_from_member(ctx_or_interaction, user_id, username)
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                if channel.guild_id and user_id:
                    member = await bot.rest.fetch_member(channel.guild_id, user_id)
                    display_name = member.nickname or member.display_name or username
                else:
                    display_name = username
            except Exception:
                display_name = username
        else:
            display_name = username

        public_key = selected_repeater.get('public_key', '')
        if not public_key:
            error_msg = f"{CROSS} Error: Repeater has no public key"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_msg,
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
            else:
                await ctx_or_interaction.respond(error_msg, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Load or create owner file
        if os.path.exists(owner_file):
            try:
                with open(owner_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        owners_data = json.loads(content)
                    else:
                        owners_data = {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }
            except json.JSONDecodeError:
                owners_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }
        else:
            owners_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        # Check if this public_key already exists
        existing_owner = None
        for owner in owners_data.get('data', []):
            if owner.get('public_key', '').upper() == public_key.upper():
                existing_owner = owner
                break

        prefix = public_key[:2].upper() if public_key else '??'
        name = selected_repeater.get('name', 'Unknown')

        if existing_owner:
            # Already claimed - show who owns it
            existing_username = existing_owner.get('username', 'Unknown')
            existing_display_name = existing_owner.get('display_name', None)
            if existing_display_name:
                message = f"{WARN} Repeater {prefix}: {name} is already claimed by **{existing_display_name}**"
            else:
                message = f"{WARN} Repeater {prefix}: {name} is already claimed by **{existing_username}**"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    message,
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
            else:
                await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Add new owner entry
        owner_entry = {
            "public_key": public_key,
            "name": name,
            "username": username,  # Actual Discord username
            "display_name": display_name,  # Server nickname or display name
            "user_id": user_id
        }

        owners_data['data'].append(owner_entry)
        owners_data['timestamp'] = datetime.now().isoformat()

        # Save to file
        with open(owner_file, 'w') as f:
            json.dump(owners_data, f, indent=2)

        # Try to assign role to user
        guild_id = None
        category_id = None
        if isinstance(ctx_or_interaction, lightbulb.Context):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                guild_id = channel.guild_id
                category_id = channel.parent_id
            except Exception:
                pass
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                guild_id = channel.guild_id
                category_id = channel.parent_id
            except Exception:
                pass

        if user_id and guild_id:
            role_assigned = await assign_repeater_owner_role(user_id, guild_id, category_id)
            if role_assigned:
                message = f"{CHECK} Successfully claimed repeater {prefix}: **{name}**\n✅ Role assigned!"
            else:
                message = f"{CHECK} Successfully claimed repeater {prefix}: **{name}**"
        else:
            message = f"{CHECK} Successfully claimed repeater {prefix}: **{name}**"

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
    except Exception as e:
        logger.error(f"Error processing repeater ownership: {e}")
        error_message = f"{CROSS} Error claiming repeater: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)

async def process_repeater_removal(selected_repeater, ctx_or_interaction):
    """Process the removal of a repeater to removedNodes.json (category-specific)"""
    try:
      # Get user ID from context/interaction
        if isinstance(ctx_or_interaction, lightbulb.Context):
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        else:
            user_id = None

        if not user_id:
            error_message = f"{CROSS} Unable to identify user"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_message,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Check if user can remove this repeater
        can_remove, reason = await can_user_remove_repeater(selected_repeater, user_id, ctx_or_interaction)
        if not can_remove:
            error_message = f"{CROSS} {reason}"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_message,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Get category-specific removed nodes file
        if isinstance(ctx_or_interaction, lightbulb.Context):
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx_or_interaction)
        elif hasattr(ctx_or_interaction, 'channel_id'):
            # For ComponentInteraction, we need to create a temporary context-like object
            # or fetch the channel to get category
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                category_id = channel.parent_id
                removed_nodes_file = get_removed_nodes_file_for_category(category_id)
            except Exception:
                removed_nodes_file = "removedNodes.json"  # Fallback to default
        else:
            removed_nodes_file = "removedNodes.json"  # Fallback to default
        if os.path.exists(removed_nodes_file):
            try:
                with open(removed_nodes_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        removed_data = json.loads(content)
                    else:
                        # File is empty, create new structure
                        removed_data = {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }
            except json.JSONDecodeError:
                # File exists but contains invalid JSON, create new structure
                removed_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }
        else:
            removed_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        # Check if node already exists in removedNodes.json
        selected_prefix = selected_repeater.get('public_key', '').upper() if selected_repeater.get('public_key') else ''
        selected_name = selected_repeater.get('name', '').strip()

        already_removed = False
        for removed_node in removed_data.get('data', []):
            removed_prefix = removed_node.get('public_key', '').upper() if removed_node.get('public_key') else ''
            removed_name = removed_node.get('name', '').strip()
            if removed_prefix == selected_prefix and removed_name == selected_name:
                already_removed = True
                break

        if already_removed:
            message = f"{WARN} Repeater {selected_prefix[:2]}: {selected_name} has already been removed"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    message,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Add node to removedNodes.json
        removed_data['data'].append(selected_repeater)
        removed_data['timestamp'] = datetime.now().isoformat()

        # Save removedNodes.json
        with open(removed_nodes_file, 'w') as f:
            json.dump(removed_data, f, indent=2)

        message = f"{CHECK} Repeater {selected_prefix[:2]}: {selected_name} has been removed"

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                components=None
            )
        else:
            await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
    except Exception as e:
        logger.error(f"Error processing repeater removal: {e}")
        error_message = f"{CROSS} Error removing repeater: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)

# Sort lines by prefix (hex value)
def extract_prefix_for_sort(line):
    """Extract prefix from line for sorting (e.g., 'A1: Name' -> 'A1')"""
    try:
        # Split by ": " to separate prefix and name
        parts = line.split(": ", 1)
        if len(parts) >= 1:
            # Get the part before the colon, then split by space to get prefix
            prefix_part = parts[0].split()[-1]  # Last word before colon (the prefix)
            # Convert hex prefix to integer for proper numerical sorting
            return int(prefix_part, 16)
    except (ValueError, IndexError):
        # If prefix extraction fails, return a high value to sort to end
        return 999
    return 999

async def update_repeater_channel_name():
    """Update Discord channel name with device counts for all categories"""
    try:
        # Get all sections from config
        all_sections = config.sections()

        # Filter to only category sections (numeric section names)
        category_sections = []
        for section in all_sections:
            try:
                # Try to convert to int to see if it's a category ID
                category_id = int(section)
                # Check if it has the required keys
                if config.has_option(section, "repeater_channel_id") and config.has_option(section, "nodes_file"):
                    category_sections.append((category_id, section))
            except (ValueError, TypeError):
                # Not a numeric section, skip it
                continue

        # Update each category's repeater channel
        for category_id, section in category_sections:
            try:
                # Get category-specific files and channel
                nodes_file = config.get(section, "nodes_file", fallback="nodes.json")
                removed_nodes_file = config.get(section, "removed_nodes_file", fallback="removedNodes.json")
                reserved_nodes_file = config.get(section, "reserved_nodes_file", fallback="reservedNodes.json")
                channel_id = config.get(section, "repeater_channel_id", fallback=None)

                if not channel_id:
                    logger.debug(f"No repeater_channel_id for category {category_id}, skipping")
                    continue

                # Load category-specific nodes data
                data = load_data_from_json(nodes_file)
                if data is None:
                    logger.warning(f"Could not load {nodes_file} for category {category_id} - skipping")
                    continue

                contacts = data.get("data", []) if isinstance(data, dict) else data
                if not isinstance(contacts, list):
                    logger.warning(f"Invalid data format in {nodes_file} for category {category_id} - skipping")
                    continue

                # Filter to repeaters only and normalize field names
                repeaters = []
                for contact in contacts:
                    if not isinstance(contact, dict):
                        continue
                    # Normalize field names
                    normalize_node(contact)
                    # Only include repeaters (device_role == 2)
                    if contact.get('device_role') == 2:
                        repeaters.append(contact)

                # Filter out removed nodes (using category-specific removed file)
                repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]

                # Categorize repeaters as online/offline based on last_seen
                now = datetime.now().astimezone()
                online_count = 0
                offline_count = 0
                dead_count = 0

                for repeater in repeaters:
                    last_seen = repeater.get('last_seen')
                    if last_seen:
                        try:
                            ls = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (now - ls).days
                            if days_ago >= 12:
                                dead_count += 1
                            elif days_ago >= 3:
                                offline_count += 1
                            else:
                                online_count += 1
                        except Exception:
                            # If we can't parse the timestamp, count as offline
                            offline_count += 1
                    else:
                        # No last_seen timestamp, count as offline
                        offline_count += 1

                # Count reserved repeaters (category-specific)
                reserved_count = 0
                if os.path.exists(reserved_nodes_file):
                    try:
                        with open(reserved_nodes_file, 'r') as f:
                            reserved_data = json.load(f)
                            reserved_count = len(reserved_data.get('data', []))
                    except Exception as e:
                        logger.debug(f"Error reading {reserved_nodes_file}: {e}")

                # Format channel name with counts
                channel_name = f"{CHECK} {online_count} {WARN} {offline_count} {CROSS} {dead_count} {RESERVED} {reserved_count}"

                # Update channel name
                await bot.rest.edit_channel(int(channel_id), name=channel_name)
                # logger.info(f"Updated channel {channel_id} (category {category_id}) name to: {channel_name}")

            except Exception as e:
                logger.error(f"Error updating channel for category {category_id}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error updating channel names: {e}")

async def periodic_channel_update():
    """Periodically update channel name"""
    while True:
        try:
            await update_repeater_channel_name()
            # Update every 15 minutes (900 seconds)
            await asyncio.sleep(900)
        except Exception as e:
            logger.error(f"Error in periodic channel update: {e}")
            # Wait 60 seconds before retrying on error
            await asyncio.sleep(60)

async def check_reserved_repeater_and_add_owner(node, prefix, reserved_nodes_file="reservedNodes.json", owner_file="repeaterOwners.json"):
    """Check if a new repeater matches a reserved node and add to category-specific repeaterOwners file

    Returns:
        user_id (int | None): The user_id from the reservation if a match was found and owner was added, None otherwise
    """
    try:
        # Use the provided reserved_nodes_file (category-specific)
        if not os.path.exists(reserved_nodes_file):
            return None

        with open(reserved_nodes_file, 'r') as f:
            reserved_data = json.load(f)

        # Find matching reserved node by prefix
        matching_reservation = None
        for reserved_node in reserved_data.get('data', []):
            if reserved_node.get('prefix', '').upper() == prefix:
                matching_reservation = reserved_node
                break

        if not matching_reservation:
            return None

        # Get username, display_name, and user_id from reservation
        username = matching_reservation.get('username', 'Unknown')
        display_name = matching_reservation.get('display_name', username)  # Fallback to username if display_name not present
        user_id = matching_reservation.get('user_id', None)
        public_key = node.get('public_key', '')

        if not public_key:
            return None

        # Use the provided owner_file (category-specific)
        if os.path.exists(owner_file):
            try:
                with open(owner_file, 'r') as f:
                    owners_data = json.load(f)
            except (json.JSONDecodeError, Exception):
                owners_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }
        else:
            owners_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        # Check if this public_key already exists
        existing_owner = None
        for owner in owners_data.get('data', []):
            if owner.get('public_key', '').upper() == public_key.upper():
                existing_owner = owner
                break

        if existing_owner:
            # Already exists, skip
            return None

        # Add new owner entry
        owner_entry = {
            "public_key": public_key,
            "name": node.get('name', 'Unknown'),
            "username": username,
            "display_name": display_name,
            "user_id": user_id
        }

        owners_data['data'].append(owner_entry)
        owners_data['timestamp'] = datetime.now().isoformat()

        # Save to file
        with open(owner_file, 'w') as f:
            json.dump(owners_data, f, indent=2)

        logger.info(f"Added repeater owner: {username} (public_key: {public_key[:10]}...)")

        # Return user_id so caller can assign roles
        return user_id

    except Exception as e:
        logger.error(f"Error checking reserved repeater and adding owner: {e}")
        return None

async def check_for_new_nodes():
    """Check all category-specific nodes files for new nodes and send Discord notifications to appropriate channels"""
    global known_node_keys

    try:
        # Get all category sections from config
        all_sections = config.sections()

        # Filter to only category sections (numeric section names)
        category_sections = []
        for section in all_sections:
            try:
                # Try to convert to int to see if it's a category ID
                category_id = int(section)
                # Check if it has nodes_file and messenger_channel_id
                if config.has_option(section, "nodes_file") and config.has_option(section, "messenger_channel_id"):
                    category_sections.append((category_id, section))
            except (ValueError, TypeError):
                # Not a numeric section, skip it
                continue

        # Track all current nodes across all categories
        all_current_node_keys = set()
        all_current_nodes_map = {}  # Map public_key to (node_data, category_id, messenger_channel_id)

        # Check each category's nodes file
        for category_id, section in category_sections:
            try:
                nodes_file = config.get(section, "nodes_file", fallback="nodes.json")
                messenger_channel_id = config.get(section, "messenger_channel_id", fallback=None)
                reserved_nodes_file = config.get(section, "reserved_nodes_file", fallback="reservedNodes.json")
                owner_file = config.get(section, "owner_file", fallback="repeaterOwners.json")

                if not messenger_channel_id:
                    continue

                if not os.path.exists(nodes_file):
                    logger.debug(f"{nodes_file} not found for category {category_id} - skipping")
                    continue

                # Retry logic to handle race conditions when file is being written
                max_retries = 3
                retry_delay = 0.5  # seconds
                nodes_data = None

                for attempt in range(max_retries):
                    try:
                        # Check if file is empty before trying to parse
                        if os.path.getsize(nodes_file) == 0:
                            if attempt < max_retries - 1:
                                logger.debug(f"{nodes_file} is empty, retrying in {retry_delay}s...")
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                logger.warning(f"{nodes_file} is empty after {max_retries} attempts - skipping")
                                break

                        with open(nodes_file, 'r') as f:
                            content = f.read().strip()
                            if not content:
                                if attempt < max_retries - 1:
                                    logger.debug(f"{nodes_file} appears empty, retrying in {retry_delay}s...")
                                    await asyncio.sleep(retry_delay)
                                    continue
                                else:
                                    logger.warning(f"{nodes_file} is empty after {max_retries} attempts - skipping")
                                    break

                        # Parse JSON
                        nodes_data = json.loads(content)
                        # Normalize field names in all nodes
                        if isinstance(nodes_data, dict) and 'data' in nodes_data:
                            for node in nodes_data.get('data', []):
                                normalize_node(node)
                        break  # Success, exit retry loop

                    except json.JSONDecodeError as e:
                        if attempt < max_retries - 1:
                            logger.debug(f"Error parsing {nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            logger.error(f"Error parsing {nodes_file}: {e}")
                            break

                if nodes_data is None:
                    continue

                # Extract all current node keys and create a map with category info
                for node in nodes_data.get('data', []):
                    public_key = node.get('public_key')
                    if public_key:
                        all_current_node_keys.add(public_key)
                        # Store node with its category and channel info
                        all_current_nodes_map[public_key] = (node, category_id, messenger_channel_id, reserved_nodes_file, owner_file)

            except Exception as e:
                logger.error(f"Error processing category {category_id}: {e}")
                continue

        # If this is the first check, initialize known_node_keys (after processing all categories)
        if not known_node_keys:
            known_node_keys = all_current_node_keys.copy()
            logger.info(f"Initialized node watcher with {len(known_node_keys)} existing nodes across all categories")
            return

        # Find new nodes (across all categories)
        new_node_keys = all_current_node_keys - known_node_keys

        if new_node_keys:
            logger.info(f"Found {len(new_node_keys)} new node(s)")

            # Send notification for each new node to its category's messenger channel
            for public_key in new_node_keys:
                if public_key not in all_current_nodes_map:
                    continue

                node, category_id, messenger_channel_id, reserved_nodes_file, owner_file = all_current_nodes_map[public_key]

                # Format node information
                node_name = node.get('name', 'Unknown')
                prefix = public_key[:2].upper() if public_key else '??'

                # Fetch server emojis
                emoji_new = await get_server_emoji(int(messenger_channel_id), "meshBuddy_new")
                emoji_salute = await get_server_emoji(int(messenger_channel_id), "meshBuddy_salute")
                emoji_wcmesh = await get_server_emoji(int(messenger_channel_id), "WCMESH")

                if node.get('device_role') == 2:
                    message = f"## {emoji_new}  **NEW REPEATER ALERT**\n**{prefix}: {node_name}** has expanded our mesh!\nThank you for your service {emoji_salute}"
                    # Check if this repeater matches a reserved node and add to category-specific owner file
                    user_id = await check_reserved_repeater_and_add_owner(node, prefix, reserved_nodes_file, owner_file)

                    # If this was a reserved repeater that became active, assign roles
                    if user_id:
                        try:
                            # Get guild_id from the channel
                            channel = await bot.rest.fetch_channel(int(messenger_channel_id))
                            guild_id = channel.guild_id if channel.guild_id else None

                            if guild_id:
                                await assign_repeater_owner_role(user_id, guild_id, category_id)
                        except Exception as e:
                            logger.error(f"Error assigning roles for reserved repeater: {e}")

                    try:
                        await bot.rest.create_message(int(messenger_channel_id), content=message)
                        logger.info(f"Sent notification for new node: {prefix} - {node_name} to category {category_id} channel")
                    except Exception as e:
                        logger.error(f"Error sending new node notification to category {category_id}: {e}")

                # elif node.get('device_role') == 1:
                #     message = f"## {emoji_new}  **NEW COMPANION ALERT**\nSay hi to **{node_name}** on West Coast Mesh {emoji_wcmesh} 927.875"

        # Update known_node_keys (with all nodes from all categories)
        known_node_keys = all_current_node_keys.copy()

    except Exception as e:
        logger.error(f"Error checking for new nodes: {e}")

async def periodic_node_watcher():
    """Periodically check for new nodes in nodes.json"""
    # Wait a bit for the bot to fully start
    await asyncio.sleep(10)

    while True:
        try:
            await check_for_new_nodes()
            # Check every 30 seconds
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error in periodic node watcher: {e}")
            # Wait 60 seconds before retrying on error
            await asyncio.sleep(60)

async def purge_old_messages_from_channel(channel_id: int, log_prefix: str = "") -> tuple[int, int]:
    """
    Purge messages older than configured days from a channel (default: 4 days from config).

    Args:
        channel_id: The ID of the channel to purge
        log_prefix: Optional prefix for log messages

    Returns:
        Tuple of (deleted_count, failed_count)
    """
    # Use semaphore to ensure only one purge operation at a time
    async with purge_semaphore:
        deleted_count = 0
        failed_count = 0

        try:
            target_channel = await bot.rest.fetch_channel(channel_id)

            # Check if channel is a text channel, news channel, or forum channel
            is_forum = isinstance(target_channel, hikari.GuildForumChannel)
            if not isinstance(target_channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel, hikari.GuildForumChannel)):
                logger.debug(f"{log_prefix}Skipping channel {channel_id}: not a text, news, or forum channel")
                return (0, 0)

            # Get guild to check permissions
            if not target_channel.guild_id:
                logger.debug(f"{log_prefix}Skipping channel {channel_id}: not a guild channel")
                return (0, 0)

            # Check if bot has MANAGE_MESSAGES permission by attempting to fetch messages
            # If we can't access the channel, we'll know we don't have permission
            try:
                if is_forum:
                    # For forum channels, try to fetch threads to verify access
                    threads_response = await bot.rest.fetch_active_threads(target_channel.guild_id)
                    # Just verify we got a response (access granted)
                    _ = threads_response
                else:
                    # Try to fetch a single message to verify we have access
                    # This will fail with ForbiddenError if we don't have permission
                    async for _ in target_channel.fetch_history().limit(1):
                        break
            except hikari.ForbiddenError:
                logger.warning(f"{log_prefix}Skipping channel {channel_id}: bot lacks permission to access channel")
                return (0, 0)
            except Exception as e:
                logger.debug(f"{log_prefix}Could not verify permissions for channel {channel_id}: {e}")
                # Continue anyway, will fail gracefully when trying to delete
                pass

            # Get purge days from config (default: 4 days)
            try:
                purge_days = int(config.get("discord", "purge_days", fallback="4"))
            except (ValueError, TypeError):
                purge_days = 4

            # Calculate the cutoff time
            cutoff_time = datetime.now().astimezone() - timedelta(days=purge_days)
            cutoff_snowflake = hikari.Snowflake.from_datetime(cutoff_time)

            logger.info(f"{log_prefix}Starting purge of messages older than {purge_days} days from channel {channel_id}")

            # Handle forum channels differently - iterate through posts (threads)
            if is_forum:
                return await _purge_forum_channel(target_channel, cutoff_snowflake, log_prefix)

            # Regular text/news channel handling
            last_message_id = None

            # Fetch and delete messages in batches
            while True:
                try:
                    # Add a longer delay before fetching to avoid rate limits on fetch operations
                    await asyncio.sleep(1.0)

                    # Fetch messages (up to 100 at a time)
                    # Use fetch_history() which returns a LazyIterator
                    if last_message_id:
                        message_iterator = target_channel.fetch_history(before=last_message_id).limit(100)
                    else:
                        message_iterator = target_channel.fetch_history().limit(100)

                    # Convert iterator to list
                    messages = []
                    async for message in message_iterator:
                        messages.append(message)

                    if not messages:
                        break

                    # Filter messages older than 14 days
                    old_messages = [msg for msg in messages if msg.id < cutoff_snowflake]

                    if not old_messages:
                        # If no old messages in this batch, check if we should continue
                        if messages and messages[-1].id < cutoff_snowflake:
                            break
                        # Otherwise, continue to next batch
                        last_message_id = messages[-1].id
                        continue

                    # Delete messages individually (required for messages older than 14 days)
                    # Rate limit: 5 deletions per 5 seconds per channel
                    # Be very conservative: add delay between each deletion
                    batch_deleted = 0
                    for message in old_messages:
                        try:
                            await bot.rest.delete_message(channel_id, message.id)
                            deleted_count += 1
                            batch_deleted += 1

                            # Rate limiting: Discord allows 5 deletions per 5 seconds per channel
                            # Be very conservative - wait longer between deletions
                            if batch_deleted % 5 == 0:
                                # After every 5 deletions, wait 2 seconds to ensure we stay well under limit
                                await asyncio.sleep(2.0)
                            else:
                                # Longer delay between each deletion to spread them out more
                                await asyncio.sleep(0.5)

                        except hikari.NotFoundError:
                            # Message already deleted, skip
                            pass
                        except hikari.ForbiddenError:
                            # Don't have permission to delete this message, skip
                            failed_count += 1
                        except hikari.RateLimitError as e:
                            # Hit rate limit, wait for the retry_after time plus a buffer
                            wait_time = getattr(e, 'retry_after', 5.0)
                            # Add extra buffer to be safe
                            wait_time = max(wait_time + 1.0, 6.0)
                            logger.warning(f"{log_prefix}Rate limited, waiting {wait_time} seconds before continuing...")
                            await asyncio.sleep(wait_time)
                            # Don't retry immediately - skip this message and continue
                            # The rate limit bucket needs time to reset
                            failed_count += 1
                            # Reset batch counter to avoid compounding delays
                            batch_deleted = 0
                        except Exception as e:
                            logger.error(f"{log_prefix}Error deleting message {message.id} from channel {channel_id}: {e}")
                            failed_count += 1

                    # Update last_message_id for next batch
                    if messages:
                        last_message_id = messages[-1].id

                    # If we didn't find any old messages in this batch and the newest is recent, we're done
                    if not old_messages and messages and messages[-1].id >= cutoff_snowflake:
                        break

                    # Longer delay between batches to avoid rate limits (especially for fetching)
                    # This helps prevent hitting rate limits on the fetch_history endpoint
                    await asyncio.sleep(3.0)

                except hikari.NotFoundError:
                    logger.warning(f"{log_prefix}Channel {channel_id} not found or no access")
                    break
                except hikari.RateLimitError as e:
                    # Hit rate limit while fetching, wait and retry
                    wait_time = getattr(e, 'retry_after', 5.0)
                    # Add extra buffer to be safe
                    wait_time = max(wait_time + 1.0, 6.0)
                    logger.warning(f"{log_prefix}Rate limited while fetching, waiting {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    # Continue the loop to retry
                    continue
                except Exception as e:
                    logger.error(f"{log_prefix}Error fetching messages from channel {channel_id}: {e}")
                    # Wait a bit before retrying to avoid hammering the API
                    await asyncio.sleep(2)
                    break

            if deleted_count > 0 or failed_count > 0:
                logger.info(f"{log_prefix}Purge complete for channel {channel_id}: deleted {deleted_count}, failed {failed_count}")

            return (deleted_count, failed_count)

        except Exception as e:
            logger.error(f"{log_prefix}Error purging channel {channel_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return (0, 0)

async def _purge_forum_channel(forum_channel: hikari.GuildForumChannel, cutoff_snowflake: hikari.Snowflake, log_prefix: str = "") -> tuple[int, int]:
    """
    Purge messages older than specified days from a forum channel by iterating through all posts (threads).

    Args:
        forum_channel: The forum channel to purge
        cutoff_snowflake: The snowflake ID representing the cutoff time
        log_prefix: Optional prefix for log messages

    Returns:
        Tuple of (deleted_count, failed_count)
    """
    deleted_count = 0
    failed_count = 0

    try:
        logger.info(f"{log_prefix}Forum channel detected, fetching all threads (posts)...")

        # Fetch active threads for this specific forum channel
        active_threads = []
        try:
            # Fetch all active threads in the guild, then filter by parent channel
            threads_response = await bot.rest.fetch_active_threads(forum_channel.guild_id)

            # Debug: inspect the response structure
            logger.debug(f"{log_prefix}Threads response type: {type(threads_response)}")
            logger.debug(f"{log_prefix}Threads response dir: {[attr for attr in dir(threads_response) if not attr.startswith('_')]}")

            # Try different ways to access threads
            threads_to_check = []

            # Method 1: Check for 'threads' attribute
            if hasattr(threads_response, 'threads'):
                threads_dict = threads_response.threads
                if isinstance(threads_dict, dict):
                    threads_to_check = list(threads_dict.values())
                elif hasattr(threads_dict, '__iter__'):
                    threads_to_check = list(threads_dict)

            # Method 2: Check if response itself is iterable or a dict
            if not threads_to_check:
                if isinstance(threads_response, dict):
                    # Check common keys
                    for key in ['threads', 'data', 'items', 'results']:
                        if key in threads_response:
                            value = threads_response[key]
                            if isinstance(value, dict):
                                threads_to_check = list(value.values())
                            elif hasattr(value, '__iter__'):
                                threads_to_check = list(value)
                            break
                elif hasattr(threads_response, '__iter__') and not isinstance(threads_response, (str, bytes)):
                    # Try iterating directly
                    try:
                        threads_to_check = list(threads_response)
                    except:
                        pass

            # Method 3: Check all attributes that might contain threads
            if not threads_to_check:
                for attr_name in ['threads', 'data', 'items', 'results', 'channels']:
                    if hasattr(threads_response, attr_name):
                        attr_value = getattr(threads_response, attr_name)
                        if isinstance(attr_value, dict):
                            threads_to_check = list(attr_value.values())
                            break
                        elif hasattr(attr_value, '__iter__') and not isinstance(attr_value, (str, bytes)):
                            threads_to_check = list(attr_value)
                            break

            logger.debug(f"{log_prefix}Found {len(threads_to_check)} threads to check")

            # Filter threads that belong to this forum channel
            for thread in threads_to_check:
                try:
                    parent_id = getattr(thread, 'parent_id', None) or getattr(thread, 'parent_channel_id', None)
                    if parent_id == forum_channel.id:
                        active_threads.append(thread)
                        logger.debug(f"{log_prefix}Found active thread: {thread.id}")
                except Exception as e:
                    logger.debug(f"{log_prefix}Error checking thread: {e}")
                    continue
        except Exception as e:
            logger.error(f"{log_prefix}Error fetching active threads: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Also fetch archived threads directly from the forum channel
        archived_threads = []
        try:
            # fetch_archived_public_threads returns an async iterator
            async for thread in forum_channel.fetch_archived_public_threads():
                archived_threads.append(thread)
                logger.debug(f"{log_prefix}Found public archived thread: {thread.id}")
        except Exception as e:
            logger.debug(f"{log_prefix}Could not fetch public archived threads: {e}")

        # Try fetching private archived threads too
        try:
            async for thread in forum_channel.fetch_archived_private_threads():
                archived_threads.append(thread)
                logger.debug(f"{log_prefix}Found private archived thread: {thread.id}")
        except Exception as e:
            logger.debug(f"{log_prefix}Could not fetch private archived threads: {e}")

        # Also try using REST API method with channel ID
        try:
            async for thread in bot.rest.fetch_public_archived_threads(channel=forum_channel.id):
                # Avoid duplicates
                if thread.id not in [t.id for t in archived_threads]:
                    archived_threads.append(thread)
                    logger.debug(f"{log_prefix}Found archived thread via REST API: {thread.id}")
        except Exception as e:
            logger.debug(f"{log_prefix}Could not fetch archived threads via REST API: {e}")

        all_threads = active_threads + archived_threads
        logger.info(f"{log_prefix}Found {len(all_threads)} thread(s) in forum channel")

        # Process each thread
        for thread in all_threads:
            try:
                # Add delay between threads to avoid rate limits
                await asyncio.sleep(1.0)

                thread_deleted = 0
                thread_failed = 0
                last_message_id = None

                # Fetch and delete messages from this thread
                while True:
                    try:
                        await asyncio.sleep(0.5)  # Delay before fetching

                        # Fetch messages from thread (threads are channels in Hikari)
                        # Need to fetch the thread as a channel first
                        thread_channel = await bot.rest.fetch_channel(thread.id)
                        if last_message_id:
                            message_iterator = thread_channel.fetch_history(before=last_message_id).limit(100)
                        else:
                            message_iterator = thread_channel.fetch_history().limit(100)

                        messages = []
                        async for message in message_iterator:
                            messages.append(message)

                        if not messages:
                            break

                        # Filter messages older than 14 days
                        old_messages = [msg for msg in messages if msg.id < cutoff_snowflake]

                        if not old_messages:
                            if messages and messages[-1].id < cutoff_snowflake:
                                break
                            last_message_id = messages[-1].id
                            continue

                        # Delete old messages
                        batch_deleted = 0
                        for message in old_messages:
                            try:
                                await bot.rest.delete_message(thread.id, message.id)
                                thread_deleted += 1
                                batch_deleted += 1

                                # Rate limiting
                                if batch_deleted % 5 == 0:
                                    await asyncio.sleep(2.0)
                                else:
                                    await asyncio.sleep(0.5)

                            except hikari.NotFoundError:
                                pass
                            except hikari.ForbiddenError:
                                thread_failed += 1
                            except hikari.RateLimitError as e:
                                wait_time = max(getattr(e, 'retry_after', 5.0) + 1.0, 6.0)
                                logger.warning(f"{log_prefix}Rate limited in thread {thread.id}, waiting {wait_time} seconds...")
                                await asyncio.sleep(wait_time)
                                thread_failed += 1
                                batch_deleted = 0
                            except Exception as e:
                                logger.error(f"{log_prefix}Error deleting message {message.id} from thread {thread.id}: {e}")
                                thread_failed += 1

                        if messages:
                            last_message_id = messages[-1].id

                        if not old_messages and messages and messages[-1].id >= cutoff_snowflake:
                            break

                        await asyncio.sleep(2.0)  # Delay between batches

                    except hikari.NotFoundError:
                        # Thread not found or no access
                        break
                    except hikari.RateLimitError as e:
                        wait_time = max(getattr(e, 'retry_after', 5.0) + 1.0, 6.0)
                        logger.warning(f"{log_prefix}Rate limited while fetching thread {thread.id}, waiting {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                        continue
                    except Exception as e:
                        logger.error(f"{log_prefix}Error fetching messages from thread {thread.id}: {e}")
                        break

                deleted_count += thread_deleted
                failed_count += thread_failed

                if thread_deleted > 0:
                    logger.info(f"{log_prefix}Deleted {thread_deleted} message(s) from thread {thread.id}")

            except Exception as e:
                logger.error(f"{log_prefix}Error processing thread {thread.id}: {e}")
                continue

        return (deleted_count, failed_count)

    except Exception as e:
        logger.error(f"{log_prefix}Error purging forum channel: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return (0, 0)

async def periodic_message_purge():
    """Periodically purge messages older than configured days from all configured messenger channels"""
    # Wait for bot to fully start
    await asyncio.sleep(30)

    while True:
        try:
            # Get all feed channel IDs from config
            channel_ids = set()

            # Add global feed channel if configured
            global_feed_id = config.get("discord", "feed_channel_id", fallback=None)
            if global_feed_id:
                try:
                    channel_ids.add(int(global_feed_id))
                except (ValueError, TypeError):
                    pass

            # Add category-specific feed channels
            for section in config.sections():
                try:
                    # Try to convert to int to see if it's a category ID
                    category_id = int(section)
                    # Check if it has feed_channel_id
                    feed_id = config.get(section, "feed_channel_id", fallback=None)
                    if feed_id:
                        try:
                            channel_ids.add(int(feed_id))
                        except (ValueError, TypeError):
                            pass
                except (ValueError, TypeError):
                    # Not a numeric section, skip
                    continue

            if not channel_ids:
                logger.debug("No feed channels configured for automatic purge")
            else:
                logger.info(f"Starting automatic purge of {len(channel_ids)} feed channel(s)")
                total_deleted = 0
                total_failed = 0

                for channel_id in channel_ids:
                    deleted, failed = await purge_old_messages_from_channel(
                        channel_id,
                        log_prefix=f"[Auto-purge] "
                    )
                    total_deleted += deleted
                    total_failed += failed
                    # Much longer delay between channels to avoid rate limits
                    # This is critical when purging multiple channels to avoid hitting global rate limits
                    await asyncio.sleep(10)

                if total_deleted > 0 or total_failed > 0:
                    logger.info(f"Automatic purge complete: {total_deleted} deleted, {total_failed} failed across {len(channel_ids)} channel(s)")

            # Run once per day (86400 seconds)
            await asyncio.sleep(86400)

        except Exception as e:
            logger.error(f"Error in periodic message purge: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Wait 1 hour before retrying on error
            await asyncio.sleep(3600)

async def send_long_message(ctx, header, lines, footer=None, max_length=2000):
    """Send a message that may exceed Discord's character limit by splitting into multiple messages"""
    if not lines:
        message = header
        if footer:
            message += f"\n\n{footer}"
        await ctx.respond(message)
        return

    footer_len = len(footer) + 2 if footer else 0  # +2 for \n\n before footer

    # Split lines into chunks
    chunks = []
    current_chunk = []
    is_first_chunk = True

    for line in lines:
        # Calculate current chunk length if we were to build the message
        if current_chunk:
            if is_first_chunk:
                current_message = f"{header}\n" + "\n".join(current_chunk)
            else:
                current_message = "\n".join(current_chunk)
        else:
            current_message = ""

        # Calculate what the message would look like with this new line
        if is_first_chunk:
            if current_message:
                test_message = current_message + "\n" + line
            else:
                test_message = f"{header}\n" + line
        else:
            if current_message:
                test_message = current_message + "\n" + line
            else:
                test_message = line

        # Reserve space for footer (conservative: assume this might be last chunk)
        if footer:
            test_length = len(test_message) + footer_len
        else:
            test_length = len(test_message)

        if test_length <= max_length:
            current_chunk.append(line)
        else:
            if current_chunk:
                chunks.append((current_chunk, is_first_chunk))
                is_first_chunk = False
            current_chunk = [line]

    if current_chunk:
        chunks.append((current_chunk, is_first_chunk))

    # Send messages
    footer_added = False
    for i, (chunk, has_header) in enumerate(chunks):
        is_last = (i == len(chunks) - 1)

        if has_header:
            message = f"{header}\n" + "\n".join(chunk)
        else:
            message = "\n".join(chunk)

        # Try to add footer to last chunk
        if footer and is_last:
            test_message = message + f"\n\n{footer}"
            if len(test_message) <= max_length:
                message = test_message
                footer_added = True

        if i == 0:
            await ctx.respond(message)
        else:
            # Send as regular channel messages back to back
            await bot.rest.create_message(
                ctx.channel_id,
                content=message
            )

    # If footer didn't fit in last chunk, send it separately
    if footer and not footer_added:
        if len(footer) <= max_length:
            await bot.rest.create_message(
                ctx.channel_id,
                content=footer
            )

# Start periodic updates when bot starts
@bot.listen()
async def on_starting(event: hikari.StartingEvent):
    """Start periodic channel updates and node watcher when bot starts"""
    # Initialize emojis after a short delay to ensure bot is ready
    async def init_emojis_delayed():
        await asyncio.sleep(5)  # Wait for bot to be fully ready
        await initialize_emojis()

    asyncio.create_task(init_emojis_delayed())
    asyncio.create_task(periodic_channel_update())
    asyncio.create_task(periodic_node_watcher())
    asyncio.create_task(periodic_message_purge())

@client.register()
class ListRepeatersCommand(lightbulb.SlashCommand, name="list",
    description="Get list of active repeaters", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of active repeaters"""
        try:
            # Load nodes data based on the category where the command was invoked
            data = await get_nodes_data_for_context(ctx)
            if data is None:
                await ctx.respond("Error retrieving repeater list.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            contacts = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(contacts, list):
                await ctx.respond("Error retrieving repeater list.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Filter to repeaters only and normalize field names
            repeaters = []
            for contact in contacts:
                if not isinstance(contact, dict):
                    continue
                # Normalize field names
                normalize_node(contact)
                # Only include repeaters (device_role == 2)
                if contact.get('device_role') == 2:
                    repeaters.append(contact)

            # Filter out removed nodes (category-specific)
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]

            # Track active repeater prefixes to avoid duplicates
            active_prefixes = set()

            lines = []
            active_repeater_count = 0  # Track count of active repeaters only
            now = datetime.now().astimezone()

            # Add active repeaters
            if repeaters:
                for contact in repeaters:
                    prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
                    name = contact.get('name', 'Unknown')
                    active_prefixes.add(prefix.upper())
                    last_seen = contact.get('last_seen')

                    # Check if within the specified days window
                    within_window = False
                    days_ago = None

                    if last_seen:
                        try:
                            ls = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (now - ls).days
                            within_window = days_ago <= self.days
                        except Exception as e:
                            logger.debug(f"Error parsing last_seen for {prefix}: {e}")
                            # If we can't parse the timestamp, still show the node but mark it
                            within_window = True  # Show it anyway

                    # Only show nodes within the specified days window
                    if within_window or days_ago is None:
                        active_repeater_count += 1  # Count this active repeater
                        if days_ago is None:
                            # No valid last_seen timestamp
                            lines.append(f"⚪ {prefix}: {name} (no timestamp)")
                        elif days_ago >= 12:
                            lines.append(f"{CROSS} {prefix}: {name} ({days_ago} days ago)") # red
                        elif days_ago >= 3:
                            lines.append(f"{WARN} {prefix}: {name} ({days_ago} days ago)") # yellow
                        else:
                            lines.append(f"{CHECK} {prefix}: {name}")

            # Add reserved nodes that aren't already active
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if os.path.exists(reserved_nodes_file):
                try:
                    with open(reserved_nodes_file, 'r') as f:
                        reserved_data = json.load(f)
                        for node in reserved_data.get('data', []):
                            prefix = node.get('prefix', '').upper()
                            name = node.get('name', 'Unknown')
                            # Only add if not already in active repeaters
                            if prefix and prefix not in active_prefixes:
                                lines.append(f"{RESERVED} {prefix}: {name}")
                except Exception as e:
                    logger.debug(f"Error reading reserved nodes file: {e}")

            lines.sort(key=extract_prefix_for_sort)

            if lines:
                header = "Active Repeaters:"
                footer = f"Total Active Repeaters: {active_repeater_count}"
                await send_long_message(ctx, header, lines, footer)
            else:
                await ctx.respond("No active repeaters found.")
        except Exception as e:
            logger.error(f"Error in list command: {e}")
            await ctx.respond("Error retrieving repeater list.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class OfflineRepeatersCommand(lightbulb.SlashCommand, name="offline",
    description="Get list of offline repeaters", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of offline repeaters"""
        try:
            devices = await get_extract_device_types_for_context(ctx, device_types=['repeaters'], days=self.days)
            if devices is None:
                await ctx.respond("Error retrieving offline repeaters.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            repeaters = devices.get('repeaters', [])
            # Filter out removed nodes (category-specific)
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]
            if repeaters:
                lines = []
                now = datetime.now().astimezone()
                for contact in repeaters:
                    prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
                    name = contact.get('name', 'Unknown')
                    last_seen = contact.get('last_seen')
                    try:
                        if last_seen:
                            ls = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (now - ls).days
                            if days_ago >= 12:
                                lines.append(f"{CROSS} {prefix}: {name} (last seen: {days_ago} days ago)") # red
                            elif days_ago >= 3:
                                lines.append(f"{WARN} {prefix}: {name} (last seen: {days_ago} days ago)") # yellow
                    except Exception:
                        pass

                header = "Offline Repeaters:"
                footer = f"Total Repeaters: {len(lines)}"
                await send_long_message(ctx, header, lines, footer)
            else:
                await ctx.respond("No offline repeaters found.")
        except Exception as e:
            logger.error(f"Error in offline command: {e}")
            await ctx.respond("Error retrieving offline repeaters.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class OpenKeysCommand(lightbulb.SlashCommand, name="open",
    description="Get list of unused hex keys", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of unused hex keys"""
        try:
            unused_keys = await get_unused_keys_for_context(ctx, days=self.days)
            if unused_keys:
                # Group keys by tens digit (first hex digit)
                grouped_keys = {}
                for key in unused_keys:
                    tens_digit = key[0]  # First character of hex (0-9, A-F)
                    if tens_digit not in grouped_keys:
                        grouped_keys[tens_digit] = []
                    grouped_keys[tens_digit].append(key)

                # Format keys with each tens group on its own line
                lines = []
                for tens in sorted(grouped_keys.keys()):
                    keys_in_group = sorted(grouped_keys[tens], key=lambda x: int(x[1], 16))
                    lines.append(" ".join(f"{key:>2}" for key in keys_in_group))

                message = f"Unused Keys ({len(unused_keys)} total):\n" + "\n".join(lines)
            else:
                message = "All 256 keys (00-FF) are currently in use!"

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in open command: {e}")
            await ctx.respond("Error retrieving unused keys.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class DuplicateKeysCommand(lightbulb.SlashCommand, name="dupes",
    description="Get list of duplicate repeater prefixes", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of duplicate repeater prefixes"""
        try:
            devices = await get_extract_device_types_for_context(ctx, device_types=['repeaters'], days=self.days)
            if devices is None:
                await ctx.respond("Error retrieving duplicate prefixes.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            repeaters = devices.get('repeaters', [])
             # Filter out removed nodes (category-specific)
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]
            if repeaters:
                # Group repeaters by prefix
                by_prefix = {}
                for repeater in repeaters:
                    public_key = (repeater.get('public_key', '').upper() if repeater.get('public_key') else '')
                    if public_key:
                        prefix = public_key[:2]
                        by_prefix.setdefault(prefix, []).append(repeater)

                lines = []
                now = datetime.now().astimezone()
                for prefix, group in sorted(by_prefix.items()):
                    names = {repeater.get('name', 'Unknown') for repeater in group}
                    if len(group) > 1 and len(names) > 1:
                        for repeater in group:
                            name = repeater.get('name', 'Unknown')
                            last_seen = repeater.get('last_seen')
                            try:
                                if last_seen:
                                    ls = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                                    days_ago = (now - ls).days
                                    if days_ago >= 12:
                                        lines.append(f"{CROSS} {prefix}: {name} ({days_ago} days ago)") # red
                                    elif days_ago >= 3:
                                        lines.append(f"{WARN} {prefix}: {name} ({days_ago} days ago)") # yellow
                                    else:
                                        lines.append(f"{CHECK} {prefix}: {name}")
                            except Exception:
                                pass

                message = "Duplicate Repeater Prefixes:\n" + "\n".join(lines)
            else:
                message = "No duplicate prefixes found."

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in dupes command: {e}")
            await ctx.respond("Error retrieving duplicate prefixes.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class CheckPrefixCommand(lightbulb.SlashCommand, name="prefix",
    description="Check if a hex prefix is available", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')
    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Check if a hex prefix is available and list all nodes with that prefix"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/prefix A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Collect all nodes with this prefix
            active_nodes = []
            reserved_nodes = []

            # Check nodes JSON file first (active repeaters)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=self.days)

            # Filter out removed nodes (category-specific)
            if repeaters:
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]

            active_nodes = repeaters

            # Check reserved nodes file
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if os.path.exists(reserved_nodes_file):
                try:
                    with open(reserved_nodes_file, 'r') as f:
                        reserved_data = json.load(f)
                        for node in reserved_data.get('data', []):
                            if node.get('prefix', '').upper() == hex_prefix:
                                reserved_nodes.append(node)
                except Exception as e:
                    logger.debug(f"Error reading reserved nodes file: {e}")

            # Build response message
            message_parts = []

            if active_nodes or reserved_nodes:
                # Prefix is in use or reserved
                message_parts.append(f"{CROSS} {hex_prefix} is **NOT AVAILABLE**\nPrefix used by:")

                # List active nodes
                if active_nodes:
                  message_parts.append(f"\nActive Repeater(s):")
                    for i, repeater in enumerate(active_nodes, 1):
                        if isinstance(repeater, dict):
                            name = repeater.get('name', 'Unknown')
                            message_parts.append(f"{name}")
                        else:
                            message_parts.append(f"(data error)")

                # List reserved nodes
                if reserved_nodes:
                    message_parts.append(f"\nReserved:")
                    for i, node in enumerate(reserved_nodes, 1):
                        name = node.get('name', 'Unknown')
                        display_name = node.get('display_name', node.get('username', 'Unknown'))
                        message_parts.append(f"{name} (reserved by {display_name})")

                # Summary
                total = len(active_nodes) + len(reserved_nodes)
                if total = 0:
                    message_parts.append(f"\n{CHECK} {hex_prefix} is **AVAILABLE** for use!")
            else:
                # Check if prefix is in unused keys
                unused_keys = await get_unused_keys_for_context(ctx, days=self.days)

                if unused_keys and hex_prefix in unused_keys:
                    message_parts.append(f"{CHECK} {hex_prefix} is **AVAILABLE** for use!")
                else:
                    message_parts.append(f"{CROSS} {hex_prefix} is **NOT AVAILABLE** (may be in use or removed)")

            message = "\n".join(message_parts)
            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in prefix command: {e}")
            await ctx.respond("Error checking prefix availability.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class RepeaterStatsCommand(lightbulb.SlashCommand, name="stats",
    description="Get the stats of a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')
    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get the stats of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/prefix A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get repeaters (now returns a list)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=self.days)

            # Filter out removed nodes (category-specific)
            if repeaters:
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]

            if repeaters and len(repeaters) > 0:
                if len(repeaters) == 1:
                    # Single repeater - show detailed info
                    repeater = repeaters[0]
                    if not isinstance(repeater, dict):
                        await ctx.respond("Error: Invalid repeater data", flags=hikari.MessageFlag.EPHEMERAL)
                        return

                    name = repeater.get('name', 'Unknown')
                    public_key = repeater.get('public_key', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')
                    location = repeater.get('location', {'latitude': 0, 'longitude': 0}) or {'latitude': 0, 'longitude': 0}
                    lat = location.get('latitude', 0)
                    lon = location.get('longitude', 0)
                    battery = repeater.get('battery_voltage', 0)

                    # Format last_seen timestamp
                    formatted_last_seen = "Unknown"
                    if last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                            formatted_last_seen = last_seen_dt.strftime("%B %d, %Y %I:%M %p")
                        except Exception:
                            formatted_last_seen = "Invalid timestamp"

                    message = f"Repeater {hex_prefix}:\nName: {name}\nKey: {public_key}\nLast Seen: {formatted_last_seen}\nLocation: {lat}, {lon}\n"

                    if battery != 0:
                        message += f"Battery Voltage: {battery} V\n"
                else:
                    # Multiple repeaters - show summary
                    message = f"Found {len(repeaters)} repeater(s) with prefix {hex_prefix}:\n\n"
                    for i, repeater in enumerate(repeaters, 1):
                        if not isinstance(repeater, dict):
                            continue

                        name = repeater.get('name', 'Unknown')
                        public_key = repeater.get('public_key', 'Unknown')
                        last_seen = repeater.get('last_seen', 'Unknown')
                        location = repeater.get('location', {'latitude': 0, 'longitude': 0}) or {'latitude': 0, 'longitude': 0}
                        lat = location.get('latitude', 0)
                        lon = location.get('longitude', 0)
                        battery = repeater.get('battery_voltage', 0)

                        # Format last_seen timestamp
                        formatted_last_seen = "Unknown"
                        if last_seen != 'Unknown':
                            try:
                                last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                                formatted_last_seen = last_seen_dt.strftime("%B %d, %Y %I:%M %p")
                            except Exception:
                                formatted_last_seen = "Invalid timestamp"

                        message += f"**#{i}:** {name}\nKey: {public_key}\nLast Seen: {formatted_last_seen}\nLocation: {lat}, {lon}\n"
                        if battery != 0:
                            message += f"Battery Voltage: {battery} V\n"
                        message += "\n"
            else:
                message = f"No repeater found with prefix {hex_prefix}."

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await ctx.respond("Error retrieving repeater stats.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class ReserveRepeaterCommand(lightbulb.SlashCommand, name="reserve",
    description="Reserve a hex prefix for a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')
    name = lightbulb.string('name', 'Repeater name')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Reserve a hex prefix for a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            name = self.name.strip()

            # First, check if prefix is currently in use by an active repeater (within last 14 days)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=14)
            if repeaters:
                # Filter out removed nodes (category-specific)
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]
                if repeaters:
                    repeater = repeaters[0]
                    current_name = repeater.get('name', 'Unknown')
                    await ctx.respond(
                        f"{CROSS} Prefix {hex_prefix} is **NOT AVAILABLE** - currently in use by: **{current_name}**\n"
                        f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                    )
                    return

            # Check if prefix is in unused keys (available for reservation) - uses 14 days
            unused_keys = await get_unused_keys_for_context(ctx, days=14)
            if unused_keys is None:
                await ctx.respond("Error: Could not check prefix availability. Please try again.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # If prefix is not in unused keys, it's not available
            if hex_prefix not in unused_keys:
                await ctx.respond(
                    f"{CROSS} Prefix {hex_prefix} is **NOT AVAILABLE** for reservation.\n"
                    f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*",
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                return

            # Load existing reservedNodes.json or create new structure (category-specific)
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if os.path.exists(reserved_nodes_file):
                with open(reserved_nodes_file, 'r') as f:
                    reserved_data = json.load(f)
            else:
                reserved_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }

            # Check if prefix already exists in reserved list
            existing_node = None
            for node in reserved_data['data']:
                if node.get('prefix', '').upper() == hex_prefix:
                    existing_node = node
                    break

            if existing_node:
                existing_name = existing_node.get('name', 'Unknown')
                existing_display_name = existing_node.get('display_name', existing_node.get('username', 'Unknown'))
                await ctx.respond(
                    f"{CROSS} {hex_prefix} with name: **{existing_name}** has already been reserved by **{existing_display_name}**\n",
                    f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                )
                return
            # Get username and user_id from context
            username = ctx.user.username if ctx.user else "Unknown"
            user_id = ctx.user.id if ctx.user else None

            # Fetch and save the user's display name (server nickname if available)
            display_name = await get_user_display_name_from_member(ctx, user_id, username)

            # Create node entry - save both username and display_name, and also save user_id
            node_entry = {
                "prefix": hex_prefix,
                "name": name,
                "username": username,  # Actual Discord username
                "display_name": display_name,  # Display name (nickname if available, otherwise username)
                "user_id": user_id,
                "added_at": datetime.now().isoformat()
            }

            # Add new entry
            reserved_data['data'].append(node_entry)
            message = f"{CHECK} Reserved hex prefix {hex_prefix} for repeater: **{name}**"

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in reserve command: {e}")
            await ctx.respond(f"Error reserving hex prefix for repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class ReleaseRepeaterCommand(lightbulb.SlashCommand, name="release",
    description="Release a hex prefix for a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Release a hex prefix for a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load existing reservedNodes.json (category-specific)
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if not os.path.exists(reserved_nodes_file):
                await ctx.respond("Error: list does not exist)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            with open(reserved_nodes_file, 'r') as f:
                reserved_data = json.load(f)

            # Find the entry to remove
            initial_count = len(reserved_data['data'])
            reserved_data['data'] = [
                node for node in reserved_data['data']
                if node.get('prefix', '').upper() != hex_prefix
            ]
            removed_count = initial_count - len(reserved_data['data'])

            if removed_count == 0:
                await ctx.respond(f"{CROSS} {hex_prefix} is not reserved for a repeater")
                return

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            message = f"{CHECK} Released hex prefix {hex_prefix}"
            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in release command: {e}")
            await ctx.respond(f"Error releasing hex prefix: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class RemoveNodeCommand(lightbulb.SlashCommand, name="remove",
    description="Remove a repeater from the repeater list", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Remove a node from nodes.json and copy it to removedNodes.json"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json (category-specific)
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    # Check if already removed using category-specific removed nodes file
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed_in_file(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}")
                return

            # If multiple repeaters found, show select menu
            if len(matching_repeaters) > 1:
                # Create select menu options
                options = []
                for i, repeater in enumerate(matching_repeaters):
                    name = repeater.get('name', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')

                    # Format last_seen for display
                    formatted_last_seen = "Unknown"
                    if last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (datetime.now(last_seen_dt.tzinfo) - last_seen_dt).days
                            formatted_last_seen = f"{days_ago} days ago"
                        except Exception:
                            formatted_last_seen = "Invalid timestamp"

                    # Create option label (Discord limit: 100 chars)
                    label = f"{name[:50]}"  # Truncate name if too long
                    description = f"Last seen: {formatted_last_seen}"[:100]

                    # Use index as value
                    options.append(
                        hikari.SelectMenuOption(
                            label=label,
                            description=description,
                            value=str(i),
                            emoji=EMOJIS[i],
                            is_default=False
                        )
                    )

                # Create custom ID for this selection
                custom_id = f"remove_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters for later retrieval
                pending_remove_selections[custom_id] = matching_repeaters

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to remove",
                    min_values=1,
                    max_values=1
                )

                for option in options:
                    select_menu_builder.add_option(
                        option.label,  # label must be positional
                        option.value,  # value must be positional
                        description=option.description,
                        emoji=option.emoji,
                        is_default=option.is_default
                    )

                # Build the action row - action_row_builder should have the select menu added to it
                # print(action_row_builder.build())
                # action_row = action_row_builder.build()

                await ctx.respond(
                    f"Found {len(matching_repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder]
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, use it directly
                selected_repeater = matching_repeaters[0]

            # Process the removal (for single repeater case)
            await process_repeater_removal(selected_repeater, ctx)
        except Exception as e:
            logger.error(f"Error in remove command: {e}")
            await ctx.respond(f"Error removing repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class OwnRepeaterCommand(lightbulb.SlashCommand, name="own",
    description="Claim ownership of a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Claim ownership of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json (category-specific)
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed_in_file(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # If multiple repeaters found, show select menu
            if len(matching_repeaters) > 1:
                # Create select menu options
                options = []
                for i, repeater in enumerate(matching_repeaters):
                    name = repeater.get('name', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')

                    # Format last_seen for display
                    formatted_last_seen = "Unknown"
                    if last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (datetime.now(last_seen_dt.tzinfo) - last_seen_dt).days
                            formatted_last_seen = f"{days_ago} days ago"
                        except Exception:
                            formatted_last_seen = "Invalid timestamp"

                    # Create option label (Discord limit: 100 chars)
                    label = f"{name[:50]}"  # Truncate name if too long
                    description = f"Last seen: {formatted_last_seen}"[:100]

                    # Use index as value
                    options.append(
                        hikari.SelectMenuOption(
                            label=label,
                            description=description,
                            value=str(i),
                            emoji=EMOJIS[i],
                            is_default=False
                        )
                    )

                # Create custom ID for this selection
                custom_id = f"own_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters for later retrieval
                pending_own_selections[custom_id] = matching_repeaters

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to claim",
                    min_values=1,
                    max_values=1
                )

                for option in options:
                    select_menu_builder.add_option(
                        option.label,  # label must be positional
                        option.value,  # value must be positional
                        description=option.description,
                        emoji=option.emoji,
                        is_default=option.is_default
                    )

                await ctx.respond(
                    f"Found {len(matching_repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, use it directly
                selected_repeater = matching_repeaters[0]

            # Process the ownership claim (for single repeater case)
            await process_repeater_ownership(selected_repeater, ctx)
        except Exception as e:
            logger.error(f"Error in own command: {e}")
            await ctx.respond(f"Error claiming repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class OwnerRepeaterCommand(lightbulb.SlashCommand, name="owner",
    description="Look up the owner of a repeater", hooks=[category_check], default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Look up the owner of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json (category-specific)
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed_in_file(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get owner file
            owner_file = await get_owner_file_for_context(ctx)

            # If multiple repeaters found, show select menu
            if len(matching_repeaters) > 1:
                # Create select menu options
                options = []
                for i, repeater in enumerate(matching_repeaters):
                    name = repeater.get('name', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')

                    # Format last_seen for display
                    formatted_last_seen = "Unknown"
                    if last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (datetime.now(last_seen_dt.tzinfo) - last_seen_dt).days
                            formatted_last_seen = f"{days_ago} days ago"
                        except Exception:
                            formatted_last_seen = "Invalid timestamp"

                    # Check if this repeater has an owner
                    owner_info = await get_owner_info_for_repeater(repeater, owner_file)
                    owner_status = " (claimed)" if owner_info else " (unclaimed)"

                    # Create option label (Discord limit: 100 chars)
                    label = f"{name[:45]}{owner_status}"[:100]  # Truncate name if too long
                    description = f"Last seen: {formatted_last_seen}"[:100]

                    # Use index as value
                    options.append(
                        hikari.SelectMenuOption(
                            label=label,
                            description=description,
                            value=str(i),
                            emoji=EMOJIS[i],
                            is_default=False
                        )
                    )

                # Create custom ID for this selection
                custom_id = f"owner_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters and owner file for later retrieval
                pending_owner_selections[custom_id] = (matching_repeaters, owner_file)

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to view owner",
                    min_values=1,
                    max_values=1
                )

                for option in options:
                    select_menu_builder.add_option(
                        option.label,  # label must be positional
                        option.value,  # value must be positional
                        description=option.description,
                        emoji=option.emoji,
                        is_default=option.is_default
                    )

                await ctx.respond(
                    f"Found {len(matching_repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, display owner info directly
                selected_repeater = matching_repeaters[0]
                await display_owner_info(selected_repeater, owner_file, ctx)
        except Exception as e:
            logger.error(f"Error in owner command: {e}")
            await ctx.respond(f"{CROSS} Error looking up owner: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


async def display_owner_info(repeater, owner_file: str, ctx_or_interaction):
    """Display owner information for a repeater"""
    try:
        public_key = repeater.get('public_key', '')
        name = repeater.get('name', 'Unknown')
        prefix = public_key[:2].upper() if public_key else '??'

        # Get owner info
        owner_info = await get_owner_info_for_repeater(repeater, owner_file)

        if owner_info:
            owner_username = owner_info.get('username', 'Unknown')
            owner_display_name = owner_info.get('display_name', None)
            owner_user_id = owner_info.get('user_id', None)

            message = f"Repeater **{prefix}: {name}**\n"
            if owner_display_name:
                message += f"Owner: **{owner_display_name}**"
            else:
                message += f"Owner: **{owner_username}**"
            # if owner_user_id:
            #     message += f" (<@{owner_user_id}>)"
        else:
            message = f"**Repeater {prefix}: {name}**\n"
            message += f"{WARN} No owner claimed for this repeater"

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
    except Exception as e:
        logger.error(f"Error displaying owner info: {e}")
        error_message = f"Error displaying owner information: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)


@bot.listen()
async def on_component_interaction(event: hikari.InteractionCreateEvent):
    """Handle component interactions (select menus) for remove command"""
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return

    interaction = event.interaction
    custom_id = interaction.custom_id

    # Check if this is a remove selection
    if custom_id and custom_id.startswith("remove_select_"):
        # Extract the custom_id to get the matching repeaters
        if custom_id in pending_remove_selections:
            matching_repeaters = pending_remove_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Process the removal
                await process_repeater_removal(selected_repeater, interaction)

                # Clean up the stored selection
                del pending_remove_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None
                )

    # Check if this is a QR code selection
    elif custom_id and custom_id.startswith("qr_select_"):
        # Extract the custom_id to get the matching repeaters
        if custom_id in pending_qr_selections:
            matching_repeaters = pending_qr_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Generate and send QR code
                await generate_and_send_qr(selected_repeater, interaction)

                # Clean up the stored selection
                del pending_qr_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None
                )

    # Check if this is an own/claim selection
    elif custom_id and custom_id.startswith("own_select_"):
        # Extract the custom_id to get the matching repeaters
        if custom_id in pending_own_selections:
            matching_repeaters = pending_own_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Process the ownership claim
                await process_repeater_ownership(selected_repeater, interaction)

                # Clean up the stored selection
                del pending_own_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )

    # Check if this is an owner lookup selection
    elif custom_id and custom_id.startswith("owner_select_"):
        # Extract the custom_id to get the matching repeaters and owner file
        if custom_id in pending_owner_selections:
            matching_repeaters, owner_file = pending_owner_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Display owner info
                await display_owner_info(selected_repeater, owner_file, interaction)

                # Clean up the stored selection
                del pending_owner_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )


@client.register()
class QRCodeCommand(lightbulb.SlashCommand, name="qr",
    description="Generate a QR code for adding a contact", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Generate a QR code for adding a contact"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/qr A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get repeaters (now returns a list)
            repeaters = await get_repeater_for_context(ctx, hex_prefix)

            # Filter out removed nodes (category-specific)
            if repeaters:
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed_in_file(r, removed_nodes_file)]

            if not repeaters or len(repeaters) == 0:
                await ctx.respond(f"{CROSS} No repeater found with prefix {hex_prefix}.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # If multiple repeaters found, show select menu
            if len(repeaters) > 1:
                # Create select menu options
                options = []
                for i, repeater in enumerate(repeaters):
                    name = repeater.get('name', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')

                    # Format last_seen for display
                    formatted_last_seen = "Unknown"
                    if last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (datetime.now(last_seen_dt.tzinfo) - last_seen_dt).days
                            formatted_last_seen = f"{days_ago} days ago"
                        except Exception:
                            formatted_last_seen = "Invalid timestamp"

                    # Create option label (Discord limit: 100 chars)
                    label = f"{name[:50]}"  # Truncate name if too long
                    description = f"Last seen: {formatted_last_seen}"[:100]

                    # Use index as value
                    options.append(
                        hikari.SelectMenuOption(
                            label=label,
                            description=description,
                            value=str(i),
                            emoji=EMOJIS[i],
                            is_default=False
                        )
                    )

                # Create custom ID for this selection
                custom_id = f"qr_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters for later retrieval
                pending_qr_selections[custom_id] = repeaters

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to generate QR code",
                    min_values=1,
                    max_values=1
                )

                for option in options:
                    select_menu_builder.add_option(
                        option.label,  # label must be positional
                        option.value,  # value must be positional
                        description=option.description,
                        emoji=option.emoji,
                        is_default=option.is_default
                    )

                await ctx.respond(
                    f"Found {len(repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, generate QR code directly
                selected_repeater = repeaters[0]
                await generate_and_send_qr(selected_repeater, ctx)
        except Exception as e:
            logger.error(f"Error in qr command: {e}")
            await ctx.respond(f"Error generating QR code: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class ListRemovedCommand(lightbulb.SlashCommand, name="xlist",
    description="Get list of removed repeaters"):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of removed repeaters"""
        try:
            lines = []

            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            if os.path.exists(removed_nodes_file):
                try:
                    with open(removed_nodes_file, 'r') as f:
                        removed_data = json.load(f)
                        for node in removed_data.get('data', []):
                            public_key = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                            name = node.get('name', 'Unknown')
                            if public_key and name and node.get('device_role') == 2:
                                lines.append(f"{CROSS} {public_key}: {name}")
                except Exception as e:
                    logger.debug(f"Error reading removedNodes.json: {e}")

            lines.sort(key=extract_prefix_for_sort)

            if lines:
                header = "Removed Repeaters:"
                footer = f"Total Repeaters: {len(lines)}"
                await send_long_message(ctx, header, lines, footer)
            else:
                await ctx.respond("No repeaters found.")
        except Exception as e:
            logger.error(f"Error in xlist command: {e}")
            await ctx.respond("Error retrieving removed list.", flags=hikari.MessageFlag.EPHEMERAL)


async def get_user_display_name_from_member(ctx: lightbulb.Context, user_id: int | None, username: str) -> str:
    """Get the Discord server display name (nickname if set, otherwise username) for a user by fetching the member"""
    try:
        # If we have a user_id, try to fetch the member
        if user_id:
            try:
                # Get the guild from the channel
                channel = await bot.rest.fetch_channel(ctx.channel_id)
                if channel.guild_id:
                    member = await bot.rest.fetch_member(channel.guild_id, user_id)
                    # Return nickname if set, otherwise display_name, otherwise username
                    return member.nickname or member.display_name or username
            except Exception as e:
                logger.debug(f"Error fetching member for user_id {user_id}: {e}")
                # Fall back to username if member fetch fails

        # Fall back to username if we can't get display name
        return username
    except Exception as e:
        logger.debug(f"Error getting display name: {e}")
        return username

@client.register()
class ListReservedCommand(lightbulb.SlashCommand, name="rlist",
    description="Get list of reserved repeaters"):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of reserved repeaters"""
        try:
            lines = []

            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)

            if os.path.exists(reserved_nodes_file):
                try:
                    with open(reserved_nodes_file, 'r') as f:
                        reserved_data = json.load(f)

                        for node in reserved_data.get('data', []):
                            try:
                                prefix = node.get('prefix', '').upper() if node.get('prefix') else ''
                                name = node.get('name', 'Unknown')

                                if prefix and name:
                                    # Use stored display name (was saved during reservation)
                                    display_name = node.get('display_name', 'Unknown')

                                    line = f"{RESERVED} {prefix}: {name} (reserved by {display_name})"
                                    lines.append(line)
                            except Exception:
                                # Skip individual node errors
                                continue
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing reserved nodes file {reserved_nodes_file}: {e}")
                    await ctx.respond("Error: Invalid JSON in reserved nodes file.", flags=hikari.MessageFlag.EPHEMERAL)
                    return
                except Exception as e:
                    logger.error(f"Error reading reserved nodes file {reserved_nodes_file}: {e}")
                    await ctx.respond("Error reading reserved nodes file.", flags=hikari.MessageFlag.EPHEMERAL)
                    return

            lines.sort(key=extract_prefix_for_sort)

            if lines:
                header = "Reserved Nodes:"
                footer = f"Total Reserved: {len(lines)}"
                await send_long_message(ctx, header, lines, footer)
            else:
                await ctx.respond("No reserved nodes found.")
        except Exception as e:
            logger.error(f"Error in rlist command: {e}")
            await ctx.respond("Error retrieving reserved list.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class KeygenCommand(lightbulb.SlashCommand, name="keygen",
    description="Generate a MeshCore keypair with a specific prefix", hooks=[category_check]):

    text = lightbulb.string('prefix', 'Hex prefix (e.g., F8A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Generate a MeshCore keypair with a specific prefix"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) < 1 or len(hex_prefix) > 8:
                await ctx.respond("Invalid hex format. Prefix must be 1-8 hex characters (e.g., F8, F8A1)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Validate it's valid hex
            try:
                int(hex_prefix, 16)
            except ValueError:
                await ctx.respond("Invalid hex format. Prefix must contain only hex characters (0-9, A-F)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Send initial response
            await ctx.respond(f"🔑 Generating keypair with prefix `{hex_prefix}`... This may take a moment.", flags=hikari.MessageFlag.EPHEMERAL)

            # Import keygen modules
            try:
                from meshcore_keygen import VanityConfig, VanityMode, MeshCoreKeyGenerator
            except ImportError as e:
                logger.error(f"Error importing meshcore_keygen: {e}")
                await ctx.interaction.edit_initial_response(f"{CROSS} Error: Could not import key generator module.")
                return

            # Run key generation in executor to avoid blocking
            def generate_key():
                config = VanityConfig(
                    mode=VanityMode.PREFIX,
                    target_prefix=hex_prefix,
                    max_time=90,  # 90 second timeout
                    max_iterations=100000000,  # 100M keys max
                    num_workers=2,  # Use fewer workers for Discord bot
                    batch_size=100000,  # 100K batch size
                    health_check=False,  # Disable health check for faster generation
                    verbose=False  # Disable verbose output
                )
                generator = MeshCoreKeyGenerator()
                return generator.generate_vanity_key(config)

            # Run in thread pool executor
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                key_info = await loop.run_in_executor(executor, generate_key)

            if key_info:
                # Format output as requested
                message = f"Public key: {key_info.public_hex}\nPrivate key: {key_info.private_hex}"
                await ctx.interaction.edit_initial_response(message)
            else:
                await ctx.interaction.edit_initial_response(f"{CROSS} Could not generate key with prefix `{hex_prefix}` within the time limit. Try a shorter prefix or try again.")
        except Exception as e:
            logger.error(f"Error in keygen command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await ctx.interaction.edit_initial_response(f"{CROSS} Error generating keypair: {str(e)}")
            except Exception as e:
                await ctx.respond(f"{CROSS} Error generating keypair: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class PurgeOldMessagesCommand(lightbulb.SlashCommand, name="purge",
    description="Delete old messages from a channel (uses configured purge_days)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    channel = lightbulb.channel('channel', 'Channel to purge messages from (defaults to current channel)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Delete old messages from a channel (uses purge_days from config, default: 4 days)"""
        try:
            # Determine which channel to purge
            target_channel_id = self.channel.id if self.channel else ctx.channel_id
            target_channel = await bot.rest.fetch_channel(target_channel_id)

            # Check if channel is a text channel, news channel, or forum channel
            if not isinstance(target_channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel, hikari.GuildForumChannel)):
                await ctx.respond(f"{CROSS} This command can only be used in text, news, or forum channels.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Check permissions - need MANAGE_MESSAGES permission
            if not ctx.member:
                await ctx.respond(f"{CROSS} Unable to verify permissions.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get guild to check permissions
            if not target_channel.guild_id:
                await ctx.respond(f"{CROSS} This command can only be used in guild channels.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Check if user has MANAGE_MESSAGES permission
            permissions = ctx.member.get_permissions()
            if not (permissions & hikari.Permissions.MANAGE_MESSAGES):
                await ctx.respond(f"{CROSS} You need the MANAGE_MESSAGES permission to use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get purge days from config for the message
            try:
                purge_days = int(config.get("discord", "purge_days", fallback="4"))
            except (ValueError, TypeError):
                purge_days = 4

            # Send initial response
            await ctx.respond(f"{WARN} Starting to purge messages older than {purge_days} days from <#{target_channel_id}>... This may take a while.", flags=hikari.MessageFlag.EPHEMERAL)

            # Use the shared purge function
            deleted_count, failed_count = await purge_old_messages_from_channel(target_channel_id)

            # Send completion message
            result_message = f"{CHECK} Purge complete! Deleted {deleted_count} message(s)"
            if failed_count > 0:
                result_message += f", {failed_count} message(s) could not be deleted"
            result_message += "."

            try:
                await ctx.interaction.edit_initial_response(result_message)
            except Exception as e:
                logger.error(f"Error editing initial response: {e}")
                # Try to send a follow-up message instead
                await ctx.respond(result_message, flags=hikari.MessageFlag.EPHEMERAL)

        except Exception as e:
            logger.error(f"Error in purge command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await ctx.interaction.edit_initial_response(f"{CROSS} Error purging messages: {str(e)}")
            except Exception:
                await ctx.respond(f"{CROSS} Error purging messages: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class HelpCommand(lightbulb.SlashCommand, name="help",
    description="Show all available commands", hooks=[category_check]):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Show all available commands"""
        try:
            help_message = """**Available Bot Commands:**

`/list` - Get list of active repeaters
`/offline` - Get list of offline repeaters (>3 days no advert)
`/dupes` - Get list of duplicate repeater prefixes
`/open` - Get list of unused hex keys
`/prefix <hex>` - Check if a hex prefix is available
`/rlist` - Get list of reserved repeaters
`/stats <hex>` - Get detailed stats of a repeater by hex prefix
`/qr <hex>` - Generate a QR code for adding a contact
`/reserve <prefix> <name>` - Reserve a hex prefix for a repeater
`/release <prefix>` - Release a hex prefix from the reserve list
`/remove <hex>` - Remove a repeater from the repeater list
`/own <hex>` - Claim ownership of a repeater
`/keygen <prefix>` - Generate a MeshCore keypair with a specific prefix
`/help` - Show this help message
"""

            await ctx.respond(help_message)
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.respond("Error retrieving help information.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class SetupRolesCommand(lightbulb.SlashCommand, name="setup_roles",
    description="Set up a reaction roles message (admin only)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    channel = lightbulb.channel('channel', 'Channel to post the roles message in')
    message = lightbulb.string('message', 'Message content for the roles message')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Set up a reaction roles message"""
        try:
            # Check if user is bot owner
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
                await ctx.respond(f"{CROSS} Only the bot owner can use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Determine channel - check config first, then parameter, then current channel
            target_channel_id = None

            # Check config for role_channel_id
            role_channel_id_str = config.get("discord", "role_channel_id", fallback=None)
            if role_channel_id_str:
                try:
                    target_channel_id = int(role_channel_id_str)
                except (ValueError, TypeError):
                    pass

            # Override with parameter if provided
            if self.channel:
                target_channel_id = self.channel.id

            # Fall back to current channel if nothing else
            if not target_channel_id:
                target_channel_id = ctx.channel_id

            target_channel = await bot.rest.fetch_channel(target_channel_id)

            if not isinstance(target_channel, hikari.GuildTextChannel):
                await ctx.respond(f"{CROSS} This command can only be used in text channels.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Default message if not provided
            roles_message = self.message if self.message else "**React to get roles:**\n\nReact with the emoji below to get the corresponding role!"

            # Send the message
            sent_message = await bot.rest.create_message(target_channel_id, roles_message)

            # Store the message ID in config or a file for tracking
            # For now, we'll use a simple approach - store in a JSON file
            roles_file = "reaction_roles.json"
            if os.path.exists(roles_file):
                try:
                    with open(roles_file, 'r') as f:
                        roles_data = json.load(f)
                except:
                    roles_data = {"messages": []}
            else:
                roles_data = {"messages": []}

            # Add this message to the list
            roles_data["messages"].append({
                "message_id": str(sent_message.id),
                "channel_id": str(target_channel_id),
                "guild_id": str(target_channel.guild_id) if target_channel.guild_id else None
            })

            with open(roles_file, 'w') as f:
                json.dump(roles_data, f, indent=2)

            await ctx.respond(
                f"{CHECK} Roles message created in <#{target_channel_id}>!\n"
                f"Message ID: {sent_message.id}\n\n"
                f"**Next steps:**\n"
                f"1. Use `/add_role_reaction` to add emoji-role mappings to this message\n"
                f"2. Users can then react to get roles automatically",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error in setup_roles command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.respond(f"{CROSS} Error setting up roles message: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class AddRoleReactionCommand(lightbulb.SlashCommand, name="add_role_reaction",
    description="Add an emoji-role mapping to a roles message (admin only)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    message_id = lightbulb.string('message_id', 'The message ID to add reactions to')
    emoji = lightbulb.string('emoji', 'The emoji to use (e.g., ✅ or :checkmark:)')
    role = lightbulb.role('role', 'The role to assign when this emoji is reacted')
    description = lightbulb.string('description', 'Description of what this role is for')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Add an emoji-role mapping to a roles message"""
        try:
            # Check if user is bot owner
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
                await ctx.respond(f"{CROSS} Only the bot owner can use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            message_id = int(self.message_id)
            role_id = self.role.id
            emoji_str = self.emoji.strip()
            description = self.description.strip()

            # Try to find the message
            roles_file = "reaction_roles.json"
            if not os.path.exists(roles_file):
                await ctx.respond(f"{CROSS} No roles messages found. Use `/setup_roles` first.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            with open(roles_file, 'r') as f:
                roles_data = json.load(f)

            # Find the message
            message_info = None
            for msg in roles_data.get("messages", []):
                if str(msg.get("message_id")) == str(message_id):
                    message_info = msg
                    break

            if not message_info:
                await ctx.respond(f"{CROSS} Message ID not found in roles messages.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            channel_id = int(message_info["channel_id"])

            # Add reaction to the message
            try:
                # Hikari's REST API accepts emoji as:
                # - Unicode emoji string (e.g., "✅")
                # - Custom emoji string format (e.g., "<:name:id>" or "<a:name:id>")
                # - Or we can fetch the emoji from the guild

                # Hikari's REST API accepts emoji as:
                # - Unicode emoji string (e.g., "✅")
                # - Custom emoji in format "name:id" (NOT "<:name:id>")
                # - Or fetch the emoji object from the guild

                emoji_obj = None
                is_animated = False

                # Try to parse as custom emoji first (Discord format: <:name:id> or <a:name:id>)
                if emoji_str.startswith('<') and emoji_str.endswith('>'):
                    # Custom emoji format: <:name:id> or <a:name:id>
                    parts = emoji_str[1:-1].split(':')
                    if len(parts) == 3:
                        is_animated = parts[0] == 'a'
                        emoji_name = parts[1]
                        emoji_id = parts[2]
                        # Hikari expects "name:id" format (without angle brackets)
                        emoji_obj = f"{emoji_name}:{emoji_id}"
                    else:
                        await ctx.respond(f"{CROSS} Invalid emoji format. Use a standard emoji (✅) or custom emoji format (<:name:id> or <a:name:id>).", flags=hikari.MessageFlag.EPHEMERAL)
                        return
                elif emoji_str.startswith(':') and emoji_str.endswith(':'):
                    # Emoji name format: :emoji_name: - try to find it in the guild
                    emoji_name = emoji_str[1:-1]  # Remove colons
                    try:
                        # Try to find the emoji in the guild
                        channel = await bot.rest.fetch_channel(channel_id)
                        if channel.guild_id:
                            guild = await bot.rest.fetch_guild(channel.guild_id)
                            # Search for emoji by name
                            for emoji in guild.get_emojis() or []:
                                if emoji.name == emoji_name:
                                    # Found guild emoji - use "name:id" format
                                    emoji_obj = f"{emoji.name}:{emoji.id}"
                                    is_animated = emoji.is_animated
                                    break

                        if not emoji_obj:
                            await ctx.respond(f"{CROSS} Emoji ':{emoji_name}:' not found in this guild.", flags=hikari.MessageFlag.EPHEMERAL)
                            return
                    except Exception as e:
                        logger.error(f"Error searching for guild emoji: {e}")
                        await ctx.respond(f"{CROSS} Error searching for emoji: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
                        return
                else:
                    # Unicode emoji - use as-is
                    emoji_obj = emoji_str

                if not emoji_obj:
                    await ctx.respond(f"{CROSS} Could not determine emoji format.", flags=hikari.MessageFlag.EPHEMERAL)
                    return

                await bot.rest.add_reaction(channel_id, message_id, emoji_obj)
            except Exception as e:
                logger.error(f"Error adding reaction: {e}")
                await ctx.respond(f"{CROSS} Error adding reaction to message: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Store the mapping
            if "mappings" not in roles_data:
                roles_data["mappings"] = []

            # Check if mapping already exists
            mapping_key = f"{message_id}:{emoji_str}"
            existing = False
            for mapping in roles_data["mappings"]:
                if mapping.get("message_id") == str(message_id) and mapping.get("emoji") == emoji_str:
                    mapping["role_id"] = str(role_id)
                    existing = True
                    break

            if not existing:
                roles_data["mappings"].append({
                    "message_id": str(message_id),
                    "emoji": emoji_str,
                    "role_id": str(role_id),
                    "guild_id": message_info.get("guild_id")
                })

            with open(roles_file, 'w') as f:
                json.dump(roles_data, f, indent=2)

            # Append "emoji - description" to the message
            try:
                current_message = await bot.rest.fetch_message(channel_id, message_id)
                current_content = current_message.content or ""

                # Append the new line
                new_line = f"{emoji_str} - {description}"
                updated_content = current_content
                if updated_content:
                    updated_content += "\n" + new_line
                else:
                    updated_content = new_line

                # Edit the message
                await bot.rest.edit_message(channel_id, message_id, updated_content)
            except Exception as e:
                logger.error(f"Error updating message content: {e}")
                # Don't fail the command if message update fails, just log it

            await ctx.respond(
                f"{CHECK} Added role reaction!\n"
                f"Emoji: {emoji_str}\n"
                f"Role: <@&{role_id}>\n"
                f"Description: {description}\n"
                f"Users can now react to get this role automatically.",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error in add_role_reaction command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.respond(f"{CROSS} Error adding role reaction: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class RemoveRoleReactionCommand(lightbulb.SlashCommand, name="remove_role_reaction",
    description="Remove an emoji-role mapping from a roles message (admin only)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    message_id = lightbulb.string('message_id', 'The message ID to remove reactions from')
    emoji = lightbulb.string('emoji', 'The emoji to remove (e.g., ✅ or :checkmark:)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Remove an emoji-role mapping from a roles message"""
        try:
            # Check if user is bot owner
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
                await ctx.respond(f"{CROSS} Only the bot owner can use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            message_id = int(self.message_id)
            emoji_str = self.emoji.strip()

            # Try to find the message
            roles_file = "reaction_roles.json"
            if not os.path.exists(roles_file):
                await ctx.respond(f"{CROSS} No roles messages found. Use `/setup_roles` first.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            with open(roles_file, 'r') as f:
                roles_data = json.load(f)

            # Find the message
            message_info = None
            for msg in roles_data.get("messages", []):
                if str(msg.get("message_id")) == str(message_id):
                    message_info = msg
                    break

            if not message_info:
                await ctx.respond(f"{CROSS} Message ID not found in roles messages.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            channel_id = int(message_info["channel_id"])

            # Find and remove the mapping
            mappings = roles_data.get("mappings", [])
            mapping_to_remove = None
            for mapping in mappings:
                if mapping.get("message_id") == str(message_id) and mapping.get("emoji") == emoji_str:
                    mapping_to_remove = mapping
                    break

            if not mapping_to_remove:
                await ctx.respond(f"{CROSS} No mapping found for this emoji on this message.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            role_id = mapping_to_remove.get("role_id")

            # Remove the mapping from the list
            roles_data["mappings"] = [m for m in mappings if m != mapping_to_remove]

            # Save the updated data
            with open(roles_file, 'w') as f:
                json.dump(roles_data, f, indent=2)

            # Remove the reaction from the message
            try:
                # Parse emoji for removal
                emoji_obj = None
                if emoji_str.startswith('<') and emoji_str.endswith('>'):
                    # Custom emoji format: <:name:id> or <a:name:id>
                    parts = emoji_str[1:-1].split(':')
                    if len(parts) == 3:
                        emoji_name = parts[1]
                        emoji_id = parts[2]
                        emoji_obj = f"{emoji_name}:{emoji_id}"
                elif emoji_str.startswith(':') and emoji_str.endswith(':'):
                    # Emoji name format: :emoji_name: - try to find it in the guild
                    emoji_name = emoji_str[1:-1]
                    try:
                        channel = await bot.rest.fetch_channel(channel_id)
                        if channel.guild_id:
                            guild = await bot.rest.fetch_guild(channel.guild_id)
                            for emoji in guild.get_emojis() or []:
                                if emoji.name == emoji_name:
                                    emoji_obj = f"{emoji.name}:{emoji.id}"
                                    break
                    except Exception as e:
                        logger.debug(f"Error searching for guild emoji: {e}")
                else:
                    # Unicode emoji
                    emoji_obj = emoji_str

                if emoji_obj:
                    # Remove the bot's reaction (we can't remove all reactions, but we can remove ours)
                    try:
                        # Get bot's user ID - use bot.me if available, otherwise skip
                        bot_user_id = None
                        try:
                            if hasattr(bot, 'me') and bot.me:
                                bot_user_id = bot.me.id
                        except:
                            pass

                        if bot_user_id:
                            await bot.rest.delete_reaction(channel_id, message_id, emoji_obj, bot_user_id)
                    except Exception as e:
                        logger.debug(f"Error removing bot reaction: {e}")
            except Exception as e:
                logger.error(f"Error removing reaction: {e}")

            # Remove the line from the message content
            try:
                current_message = await bot.rest.fetch_message(channel_id, message_id)
                current_content = current_message.content or ""

                # Remove the line that contains this emoji and description
                lines = current_content.split('\n')
                updated_lines = []
                for line in lines:
                    # Check if this line starts with the emoji (with optional whitespace)
                    line_stripped = line.strip()
                    if not line_stripped.startswith(emoji_str):
                        updated_lines.append(line)

                updated_content = '\n'.join(updated_lines).strip()

                # Edit the message
                if updated_content != current_content:
                    await bot.rest.edit_message(channel_id, message_id, updated_content)
            except Exception as e:
                logger.error(f"Error updating message content: {e}")
                # Don't fail the command if message update fails, just log it

            await ctx.respond(
                f"{CHECK} Removed role reaction!\n"
                f"Emoji: {emoji_str}\n"
                f"Role: <@&{role_id}>\n"
                f"The mapping has been removed and users will no longer get this role from reactions.",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error in remove_role_reaction command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.respond(f"{CROSS} Error removing role reaction: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@bot.listen()
async def on_reaction_add(event: hikari.GuildReactionAddEvent):
    """Handle reaction add events for role assignment"""
    try:
        # Ignore bot reactions
        if event.member and event.member.is_bot:
            return

        # Load reaction roles mappings
        roles_file = "reaction_roles.json"
        if not os.path.exists(roles_file):
            return

        with open(roles_file, 'r') as f:
            roles_data = json.load(f)

        # Find mapping for this message and emoji
        message_id = str(event.message_id)
        emoji_str = None

        # Handle emoji - could be UnicodeEmoji object or custom emoji
        if event.emoji_id:
            # Custom emoji
            emoji_name = str(event.emoji_name) if event.emoji_name else ""
            emoji_str = f"<:{emoji_name}:{event.emoji_id}>"
        elif event.emoji_name:
            # Unicode emoji - could be UnicodeEmoji object or string
            emoji_str = str(event.emoji_name)

        if not emoji_str:
            return

        mapping = None
        for m in roles_data.get("mappings", []):
            if m.get("message_id") == message_id:
                # Compare emoji
                mapping_emoji = m.get("emoji", "")
                if mapping_emoji == emoji_str or mapping_emoji == event.emoji_name:
                    mapping = m
                    break

        if not mapping:
            return

        # Assign the role
        role_id = int(mapping["role_id"])
        guild_id = event.guild_id

        if not guild_id or not event.user_id:
            return

        try:
            await bot.rest.add_role_to_member(guild_id, event.user_id, role_id)
            logger.info(f"Assigned role {role_id} to user {event.user_id} via reaction")
        except hikari.ForbiddenError:
            logger.warning(f"Bot doesn't have permission to assign role {role_id}")
        except Exception as e:
            logger.error(f"Error assigning role via reaction: {e}")
    except Exception as e:
        logger.error(f"Error in reaction add handler: {e}")


@bot.listen()
async def on_reaction_remove(event: hikari.GuildReactionDeleteEvent):
    """Handle reaction remove events for role removal"""
    try:
        # Load reaction roles mappings
        roles_file = "reaction_roles.json"
        if not os.path.exists(roles_file):
            return

        with open(roles_file, 'r') as f:
            roles_data = json.load(f)

        # Find mapping for this message and emoji
        message_id = str(event.message_id)
        emoji_str = None

        # Handle emoji - could be UnicodeEmoji object or string
        if event.emoji_id:
            # Custom emoji
            emoji_name = str(event.emoji_name) if event.emoji_name else ""
            emoji_str = f"<:{emoji_name}:{event.emoji_id}>"
        elif event.emoji_name:
            # Unicode emoji - could be UnicodeEmoji object or string
            emoji_str = str(event.emoji_name)

        if not emoji_str:
            return

        mapping = None
        for m in roles_data.get("mappings", []):
            if m.get("message_id") == message_id:
                # Compare emoji
                mapping_emoji = m.get("emoji", "")
                if mapping_emoji == emoji_str or mapping_emoji == str(event.emoji_name):
                    mapping = m
                    break

        if not mapping:
            return

        # GuildReactionDeleteEvent doesn't have user_id, so we need to fetch the message
        # and check who still has the reaction, then remove role from those who don't
        guild_id = event.guild_id
        channel_id = event.channel_id
        role_id = int(mapping["role_id"])

        if not guild_id or not channel_id:
            return

        try:
            # Fetch the message to get current reactions
            message = await bot.rest.fetch_message(channel_id, event.message_id)

            # Find the reaction for this emoji
            reaction = None
            reaction_emoji = None
            for r in message.reactions or []:
                # Compare reactions
                if event.emoji_id:
                    # Custom emoji
                    if r.emoji and r.emoji.id == event.emoji_id:
                        reaction = r
                        reaction_emoji = r.emoji
                        break
                elif event.emoji_name:
                    # Unicode emoji
                    if r.emoji and str(r.emoji) == str(event.emoji_name):
                        reaction = r
                        reaction_emoji = r.emoji
                        break

            # Get users who currently have the reaction
            users_with_reaction = set()
            if reaction and reaction_emoji:
                try:
                    async for user in bot.rest.fetch_reactions_for_emoji(channel_id, message_id, reaction_emoji):
                        users_with_reaction.add(user.id)
                except Exception as e:
                    logger.debug(f"Error fetching reaction users: {e}")

            # Get all members with the role
            try:
                guild = await bot.rest.fetch_guild(guild_id)
                async for member in bot.rest.fetch_members(guild_id):
                    # Check if member has the role but doesn't have the reaction
                    if role_id in member.role_ids and member.id not in users_with_reaction:
                        # Member has role but no longer has reaction - remove role
                        try:
                            await bot.rest.remove_role_from_member(guild_id, member.id, role_id)
                            logger.info(f"Removed role {role_id} from user {member.id} via reaction removal")
                        except Exception as e:
                            logger.debug(f"Error removing role from {member.id}: {e}")
            except Exception as e:
                logger.error(f"Error fetching guild members: {e}")

        except Exception as e:
            logger.error(f"Error handling reaction removal: {e}")
    except Exception as e:
        logger.error(f"Error in reaction remove handler: {e}")


if __name__ == "__main__":
    bot.run()
