"""
Bot Tasks Module

Contains background tasks and periodic functions:
- Channel name updates
- Node watcher
- Message purging
- Utility functions for long messages
"""

import json
import os
import asyncio
from datetime import datetime, timedelta
import hikari

from bot.core import bot, config, logger, CHECK, WARN, CROSS, RESERVED, known_node_keys
from bot.utils import normalize_node, get_removed_nodes_set, get_server_emoji, is_node_removed
from bot.helpers import check_reserved_repeater_and_add_owner, assign_repeater_owner_role
from helpers import load_data_from_json


# ============================================================================
# Channel Update Tasks
# ============================================================================

async def update_repeater_channel_name():
    """Update Discord channel name with device counts for the configured repeater status channel"""
    try:
        # Get repeater status channel from [discord] section
        repeater_channel_id = config.get("discord", "repeater_status_channel_id", fallback=None)
        if not repeater_channel_id:
            logger.debug("No repeater_status_channel_id configured, skipping channel update")
            return

        try:
            repeater_channel_id = int(repeater_channel_id)
        except (ValueError, TypeError):
            logger.warning(f"Invalid repeater_status_channel_id: {repeater_channel_id}")
            return

        # Use default file names
        nodes_file = "nodes.json"
        removed_nodes_file = "removedNodes.json"
        reserved_nodes_file = "reservedNodes.json"

        # Load nodes data
        data = load_data_from_json(nodes_file)
        if data is None:
            logger.warning(f"Could not load {nodes_file} - skipping")
            return

        contacts = data.get("data", []) if isinstance(data, dict) else data
        if not isinstance(contacts, list):
            logger.warning(f"Invalid data format in {nodes_file} - skipping")
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
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

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

            # Count reserved repeaters
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
            await bot.rest.edit_channel(repeater_channel_id, name=channel_name)
            # logger.info(f"Updated channel {repeater_channel_id} name to: {channel_name}")

    except Exception as e:
        logger.error(f"Error updating channel name: {e}")


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


# ============================================================================
# Node Watcher Tasks
# ============================================================================

async def check_for_new_nodes():
    """Check nodes file for new nodes and send Discord notifications to the messenger channel"""
    global known_node_keys

    try:
        # Get channels from [discord] section
        messenger_channel_id = config.get("discord", "bot_messenger_channel_id", fallback=None)
        if not messenger_channel_id:
            logger.debug("No bot_messenger_channel_id configured, skipping node watcher")
            return

        try:
            messenger_channel_id = int(messenger_channel_id)
        except (ValueError, TypeError):
            logger.warning(f"Invalid bot_messenger_channel_id: {messenger_channel_id}")
            return

        # Use default file names
        nodes_file = "nodes.json"
        reserved_nodes_file = "reservedNodes.json"
        owner_file = "repeaterOwners.json"

        if not os.path.exists(nodes_file):
            logger.debug(f"{nodes_file} not found - skipping")
            return

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
                        return

                with open(nodes_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{nodes_file} appears empty, retrying in {retry_delay}s...")
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            logger.warning(f"{nodes_file} is empty after {max_retries} attempts - skipping")
                            return

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
                    return

        if nodes_data is None:
            return

        # Extract all current node keys
        all_current_node_keys = set()
        all_current_nodes_map = {}  # Map public_key to (node_data, messenger_channel_id, reserved_nodes_file, owner_file)

        for node in nodes_data.get('data', []):
            public_key = node.get('public_key')
            if public_key:
                all_current_node_keys.add(public_key)
                # Store node with its channel info
                all_current_nodes_map[public_key] = (node, messenger_channel_id, reserved_nodes_file, owner_file)

        # If this is the first check, initialize known_node_keys
        if not known_node_keys:
            known_node_keys = all_current_node_keys.copy()
            logger.info(f"Initialized node watcher with {len(known_node_keys)} existing nodes")
            return

        # Find new nodes
        new_node_keys = all_current_node_keys - known_node_keys

        if new_node_keys:
            logger.info(f"Found {len(new_node_keys)} new node(s)")

            # Send notification for each new node to the messenger channel
            for public_key in new_node_keys:
                if public_key not in all_current_nodes_map:
                    continue

                node, messenger_channel_id, reserved_nodes_file, owner_file = all_current_nodes_map[public_key]

                # Format node information
                node_name = node.get('name', 'Unknown')
                prefix = public_key[:2].upper() if public_key else '??'

                # Fetch server emojis
                emoji_new = await get_server_emoji(int(messenger_channel_id), "meshBuddy_new")
                emoji_salute = await get_server_emoji(int(messenger_channel_id), "meshBuddy_salute")
                emoji_wcmesh = await get_server_emoji(int(messenger_channel_id), "WCMESH")

                if node.get('device_role') == 2:
                    message = f"## {emoji_new}  **NEW REPEATER ALERT**\n**{prefix}: {node_name}** has expanded our mesh!\nThank you for your service {emoji_salute}"

                    # Add location link if node has location data
                    location = node.get('location', {})
                    if isinstance(location, dict):
                        lat = location.get('latitude', 0)
                        lon = location.get('longitude', 0)
                        if lat != 0 and lon != 0:
                            # Get meshmap URL from config
                            meshmap_url = config.get("meshmap", "url", fallback=None)
                            if meshmap_url:
                                # Build URL with location query parameters
                                location_link = f"{meshmap_url}?lat={lat}&long={lon}&zoom=10"
                                message += f" [View on Map]({location_link})"

                    # Check if this repeater matches a reserved node and add to owner file
                    user_id = await check_reserved_repeater_and_add_owner(node, prefix, reserved_nodes_file, owner_file)

                # If this was a reserved repeater that became active, assign roles
                if user_id:
                    try:
                        # Get guild_id from the channel
                        channel = await bot.rest.fetch_channel(messenger_channel_id)
                        guild_id = channel.guild_id if channel.guild_id else None

                        if guild_id:
                            await assign_repeater_owner_role(user_id, guild_id)
                    except Exception as e:
                        logger.error(f"Error assigning roles for reserved repeater: {e}")

                try:
                    await bot.rest.create_message(messenger_channel_id, content=message)
                    logger.info(f"Sent notification for new node: {prefix} - {node_name} to messenger channel")
                except Exception as e:
                    logger.error(f"Error sending new node notification: {e}")

            # elif node.get('device_role') == 1:
            #     message = f"## {emoji_new}  **NEW COMPANION ALERT**\nSay hi to **{node_name}** on West Coast Mesh {emoji_wcmesh} 927.875"

        # Update known_node_keys
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


# ============================================================================
# Utility Functions
# ============================================================================

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
