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
from bot.core import bot, config, logger, CHECK, WARN, CROSS, RESERVED, known_node_keys, purge_semaphore
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
            logger.error(f"Error updating channel {repeater_channel_id}: {e}")

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
# Message Purge Tasks
# ============================================================================

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

            # Add feed channel
            for section in config.sections():
                try:
                    # Try to convert to int to see if it's a channel ID
                    channel_id = int(section)
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
