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
from datetime import datetime
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
known_node_keys = set()  # Track known node public_keys

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
    logger.info(f"Category restriction enabled: commands will only work in category IDs {ALLOWED_CATEGORY_IDS}")
else:
    logger.info("No category sections found in config - commands will work in all channels")

@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS, skip_when_failed=True)
async def category_check(pl: lightbulb.ExecutionPipeline, ctx: lightbulb.Context) -> None:
    """Check if command is being executed in an allowed category"""
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

async def get_nodes_data_for_context(ctx: lightbulb.Context):
    """Get nodes data based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    nodes_file = get_nodes_file_for_category(category_id)
    return load_data_from_json(nodes_file)

async def get_repeater_for_context(ctx: lightbulb.Context, prefix: str, days: int = 7):
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

async def get_extract_device_types_for_context(ctx: lightbulb.Context, device_types=None, days=7):
    """Extract device types based on the category where the command was invoked"""
    data = await get_nodes_data_for_context(ctx)
    from helpers.device_utils import extract_device_types
    return extract_device_types(data=data, device_types=device_types, days=days)

async def get_unused_keys_for_context(ctx: lightbulb.Context, days=7):
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

async def process_repeater_removal(selected_repeater, ctx_or_interaction):
    """Process the removal of a repeater to removedNodes.json (category-specific)"""
    try:
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
                await ctx_or_interaction.respond(message)
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
            await ctx_or_interaction.respond(message)
    except Exception as e:
        logger.error(f"Error processing repeater removal: {e}")
        error_message = f"Error removing repeater: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None
            )
        else:
            await ctx_or_interaction.respond(error_message)

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
    """Check if a new repeater matches a reserved node and add to category-specific repeaterOwners file"""
    try:
        # Use the provided reserved_nodes_file (category-specific)
        if not os.path.exists(reserved_nodes_file):
            return

        with open(reserved_nodes_file, 'r') as f:
            reserved_data = json.load(f)

        # Find matching reserved node by prefix
        matching_reservation = None
        for reserved_node in reserved_data.get('data', []):
            if reserved_node.get('prefix', '').upper() == prefix:
                matching_reservation = reserved_node
                break

        if not matching_reservation:
            return

        # Get username and user_id from reservation
        username = matching_reservation.get('username', 'Unknown')
        user_id = matching_reservation.get('user_id', None)
        public_key = node.get('public_key', '')

        if not public_key:
            return

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
            return

        # Add new owner entry
        owner_entry = {
            "public_key": public_key,
            "name": node.get('name', 'Unknown'),
            "username": username,
            "user_id": user_id
        }

        owners_data['data'].append(owner_entry)
        owners_data['timestamp'] = datetime.now().isoformat()

        # Save to file
        with open(owners_file, 'w') as f:
            json.dump(owners_data, f, indent=2)

        logger.info(f"Added repeater owner: {username} (public_key: {public_key[:10]}...)")

    except Exception as e:
        logger.error(f"Error checking reserved repeater and adding owner: {e}")

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
                    await check_reserved_repeater_and_add_owner(node, prefix, reserved_nodes_file, owner_file)

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

@client.register()
class ListRepeatersCommand(lightbulb.SlashCommand, name="list",
    description="Get list of active repeaters", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of active repeaters"""
        try:
            # Load nodes data based on the category where the command was invoked
            data = await get_nodes_data_for_context(ctx)
            if data is None:
                await ctx.respond("Error retrieving repeater list.")
                return

            contacts = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(contacts, list):
                await ctx.respond("Error retrieving repeater list.")
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

            # Filter out removed nodes
            repeaters = [r for r in repeaters if not is_node_removed(r)]

            # Track active repeater prefixes to avoid duplicates
            active_prefixes = set()

            lines = []
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
                footer = f"Total Repeaters: {len(lines)}"
                await send_long_message(ctx, header, lines, footer)
            else:
                await ctx.respond("No active repeaters found.")
        except Exception as e:
            logger.error(f"Error in list command: {e}")
            await ctx.respond("Error retrieving repeater list.")


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
                await ctx.respond("Error retrieving offline repeaters.")
                return

            repeaters = devices.get('repeaters', [])
            repeaters = [r for r in repeaters if not is_node_removed(r)]
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
            await ctx.respond("Error retrieving offline repeaters.")


@client.register()
class OpenKeysCommand(lightbulb.SlashCommand, name="open",
    description="Get list of unused hex keys", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

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
            await ctx.respond("Error retrieving unused keys.")


@client.register()
class DuplicateKeysCommand(lightbulb.SlashCommand, name="dupes",
    description="Get list of duplicate repeater prefixes", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of duplicate repeater prefixes"""
        try:
            devices = await get_extract_device_types_for_context(ctx, device_types=['repeaters'], days=self.days)
            if devices is None:
                await ctx.respond("Error retrieving duplicate prefixes.")
                return

            repeaters = devices.get('repeaters', [])
            repeaters = [r for r in repeaters if not is_node_removed(r)]
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
                                    if days_ago > 12:
                                        lines.append(f"{CROSS} {prefix}: {name} ({days_ago} days ago)") # red
                                    elif days_ago > 3:
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
            await ctx.respond("Error retrieving duplicate prefixes.")


@client.register()
class CheckPrefixCommand(lightbulb.SlashCommand, name="prefix",
    description="Check if a hex prefix is available", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')
    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Check if a hex prefix is available"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/prefix A1`")
                return

            # Check nodes JSON file first (active repeaters)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=self.days)

            # Filter out removed nodes
            if repeaters:
                repeaters = [r for r in repeaters if not is_node_removed(r)]

            if repeaters and len(repeaters) > 0:
                # Prefix is actively in use
                repeater = repeaters[0]  # Get the first repeater
                if not isinstance(repeater, dict):
                    message = f"{CROSS} {hex_prefix} is **NOT AVAILABLE** (data error)"
                else:
                    name = repeater.get('name', 'Unknown')

                    message = f"{CROSS} {hex_prefix} is **NOT AVAILABLE**\n\n**Current User:**\n"
                    message += f"Name: {name}\n"

                    if len(repeaters) > 1:
                        message += f"\n\n*Note: {len(repeaters)} repeater(s) found with this prefix. use `/stats` to see them*"
                await ctx.respond(message)
                return

            # Check reserved nodes file
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if os.path.exists(reserved_nodes_file):
                try:
                    with open(reserved_nodes_file, 'r') as f:
                        reserved_data = json.load(f)
                        for node in reserved_data.get('data', []):
                            if node.get('prefix', '').upper() == hex_prefix:
                                message = f"{RESERVED} {hex_prefix} is on the **RESERVED LIST**"
                                await ctx.respond(message)
                                return
                except Exception as e:
                    logger.debug(f"Error reading reserved nodes file: {e}")

            # Get unused keys
            unused_keys = await get_unused_keys_for_context(ctx, days=self.days)

            if unused_keys and hex_prefix in unused_keys:
                message = f"{CHECK} {hex_prefix} is **AVAILABLE** for use!"
            else:
                message = f"{CROSS} {hex_prefix} is **NOT AVAILABLE** (already in use)"

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in prefix command: {e}")
            await ctx.respond("Error checking prefix availability.")


@client.register()
class RepeaterStatsCommand(lightbulb.SlashCommand, name="stats",
    description="Get the stats of a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')
    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get the stats of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/prefix A1`")
                return

            # Get repeaters (now returns a list)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=self.days)

            # Filter out removed nodes
            if repeaters:
                repeaters = [r for r in repeaters if not is_node_removed(r)]

            if repeaters and len(repeaters) > 0:
                if len(repeaters) == 1:
                    # Single repeater - show detailed info
                    repeater = repeaters[0]
                    if not isinstance(repeater, dict):
                        await ctx.respond("Error: Invalid repeater data")
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
            await ctx.respond("Error retrieving repeater stats.")


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
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`")
                return

            name = self.name.strip()

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

            # Check if prefix already exists
            existing_node = None
            for node in reserved_data['data']:
                if node.get('prefix', '').upper() == hex_prefix:
                    existing_node = node
                    break

            if existing_node:
                await ctx.respond(f"{CROSS} {hex_prefix} with name: **{name}** has already been reserved")
                return

            # Check if prefix is currently in use by an active repeater
            unused_keys = await get_unused_keys_for_context(ctx, days=7)
            if unused_keys is None:
                await ctx.respond("Error: Could not check prefix availability. Please try again.")
                return

            # Check if prefix is in unused keys (available for reservation)
            if hex_prefix not in unused_keys:
                # Prefix is currently in use - get repeater info to show who's using it
                repeaters = await get_repeater_for_context(ctx, hex_prefix, days=7)
                if repeaters:
                    # Filter out removed nodes
                    repeaters = [r for r in repeaters if not is_node_removed(r)]
                    if repeaters:
                        repeater = repeaters[0]
                        current_name = repeater.get('name', 'Unknown')
                        await ctx.respond(
                            f"{CROSS} Prefix {hex_prefix} is **NOT AVAILABLE** - currently in use by: **{current_name}**\n"
                            f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                        )
                        return

                # Prefix not in unused keys but no active repeater found (edge case)
                await ctx.respond(
                    f"{CROSS} Prefix {hex_prefix} is **NOT AVAILABLE** for reservation.\n"
                    f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                )
                return
            # Get username and user_id from context
            username = ctx.user.username if ctx.user else "Unknown"
            user_id = ctx.user.id if ctx.user else None

            # Fetch and save the user's display name (server nickname if available)
            display_name = await get_user_display_name_from_member(ctx, user_id, username)

            # Create node entry - save display name as username, and also save user_id
            node_entry = {
                "prefix": hex_prefix,
                "name": name,
                "username": display_name,  # Save display name (nickname if available, otherwise username)
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
            await ctx.respond(f"Error reserving hex prefix for repeater: {str(e)}")


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
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`")
                return

            # Load existing reservedNodes.json (category-specific)
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if not os.path.exists(reserved_nodes_file):
                await ctx.respond("Error: list does not exist)")
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
            await ctx.respond(f"Error releasing hex prefix: {str(e)}")


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
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`")
                return

            # Load nodes.json (category-specific)
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found")
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
            await ctx.respond(f"{CROSS} Error removing repeater: {str(e)}")


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

            # Filter out removed nodes
            if repeaters:
                repeaters = [r for r in repeaters if not is_node_removed(r)]

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
            await ctx.respond(f"{CROSS} Error generating QR code: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


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
            await ctx.respond("Error retrieving removed list.")


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
                                    display_name = node.get('username', 'Unknown')

                                    line = f"{RESERVED} {prefix}: {name} (reserved by {display_name})"
                                    lines.append(line)
                            except Exception:
                                # Skip individual node errors
                                continue
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing reserved nodes file {reserved_nodes_file}: {e}")
                    await ctx.respond("Error: Invalid JSON in reserved nodes file.")
                    return
                except Exception as e:
                    logger.error(f"Error reading reserved nodes file {reserved_nodes_file}: {e}")
                    await ctx.respond("Error reading reserved nodes file.")
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
            await ctx.respond("Error retrieving reserved list.")


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
class HelpCommand(lightbulb.SlashCommand, name="help",
    description="Show all available commands", hooks=[category_check]):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Show all available commands"""
        try:
            help_message = """**Available Bot Commands:**

`/list`* - Get list of active repeaters
`/offline` - Get list of offline repeaters (>3 days no advert)
`/dupes`* - Get list of duplicate repeater prefixes
`/open`* - Get list of unused hex keys
`/prefix <hex>`* - Check if a hex prefix is available
`/rlist` - Get list of reserved repeaters
`/stats <hex>`* - Get detailed stats of a repeater by hex prefix
`/qr <hex>` - Generate a QR code for adding a contact
`/reserve <prefix> <name>` - Reserve a hex prefix for a repeater
`/release <prefix>` - Release a hex prefix from the reserve list
`/remove <hex>` - Remove a repeater from the repeater list
`/keygen <prefix>` - Generate a MeshCore keypair with a specific prefix
`/help` - Show this help message

**Commands also accept an optional `days` parameter (default: 7 days)*"""

            await ctx.respond(help_message)
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.respond("Error retrieving help information.")

if __name__ == "__main__":
    bot.run()
