"""
Bot Utilities Module

Contains helper functions for file paths, category management, context helpers,
emoji management, and node utilities.
"""

import json
import os
import time
import logging
from bot.core import bot, config, logger
from helpers import load_data_from_json

logger = logging.getLogger(__name__)


# Category and Context Helpers

async def get_category_id_from_context(ctx) -> int | None:
    """Get the category ID from the context where the command was invoked"""
    try:
        channel = await bot.rest.fetch_channel(ctx.channel_id)
        return channel.parent_id
    except Exception as e:
        logger.error(f"Error getting category ID from context: {e}")
        return None


# ============================================================================
# File Path Helpers
# ============================================================================

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


async def get_reserved_nodes_file_for_context(ctx) -> str:
    """Get reserved nodes file name based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    return get_reserved_nodes_file_for_category(category_id)


async def get_removed_nodes_file_for_context(ctx) -> str:
    """Get removed nodes file name based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    return get_removed_nodes_file_for_category(category_id)


async def get_owner_file_for_context(ctx) -> str:
    """Get owner file name based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    return get_owner_file_for_category(category_id)


# ============================================================================
# Context Data Helpers
# ============================================================================

async def get_nodes_data_for_context(ctx):
    """Get nodes data based on the category where the command was invoked"""
    category_id = await get_category_id_from_context(ctx)
    nodes_file = get_nodes_file_for_category(category_id)
    return load_data_from_json(nodes_file)


async def get_repeater_for_context(ctx, prefix: str, days: int = 14):
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


async def get_extract_device_types_for_context(ctx, device_types=None, days=14):
    """Extract device types based on the category where the command was invoked"""
    data = await get_nodes_data_for_context(ctx)
    from helpers.device_utils import extract_device_types
    return extract_device_types(data=data, device_types=device_types, days=days)


async def get_unused_keys_for_context(ctx, days=14):
    """Get unused keys based on the category where the command was invoked"""
    data = await get_nodes_data_for_context(ctx)
    if data is None:
        return None

    # Load all repeaters (not filtered by days) to include future timestamps
    contacts = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(contacts, list):
        return None

    # Filter to repeaters only and normalize field names
    repeaters = []
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        # Normalize field names (normalize_node is defined later in this file)
        normalize_node(contact)
        # Only include repeaters (device_role == 2)
        if contact.get('device_role') == 2:
            repeaters.append(contact)
    # Load removed nodes to exclude them (category-specific)
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


# ============================================================================
# Emoji Helpers
# ============================================================================

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


# ============================================================================
# Node Utilities
# ============================================================================

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
    """Check if a contact node has been removed"""
    removed_set = get_removed_nodes_set(removed_nodes_file)
    prefix = contact.get('public_key', '').upper() if contact.get('public_key') else ''
    name = contact.get('name', '').strip()
    return (prefix, name) in removed_set


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
