"""
Repeater Commands

Commands for viewing and querying repeater information:
- list: Get list of active repeaters
- offline: Get list of offline repeaters
- open: Get list of unused hex keys
- dupes: Get list of duplicate repeater prefixes
- prefix: Check if a hex prefix is available
- stats: Get detailed stats of a repeater by hex prefix
"""

import json
import os
from datetime import datetime
import hikari
import lightbulb
from bot.core import client, logger, CHECK, CROSS, WARN, RESERVED, category_check, EMOJIS
from bot.utils import (
    get_nodes_data_for_context,
    get_removed_nodes_file_for_context,
    get_reserved_nodes_file_for_context,
    get_repeater_for_context,
    get_extract_device_types_for_context,
    get_unused_keys_for_context,
    normalize_node,
    is_node_removed,
    extract_prefix_for_sort
)
from bot.tasks import send_long_message


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
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

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
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
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
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
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

            # Check if hex parameter was provided
            if self.text is None:
                await ctx.respond("Please provide a hex prefix (e.g., `/prefix A1`)", flags=hikari.MessageFlag.EPHEMERAL)
                return

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
            if repeaters and isinstance(repeaters, list):
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                active_nodes = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
            else:
                active_nodes = []

            # Check reserved nodes file
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if os.path.exists(reserved_nodes_file):
                try:
                    with open(reserved_nodes_file, 'r') as f:
                        reserved_data = json.load(f)
                        if reserved_data and isinstance(reserved_data, dict):
                            data_list = reserved_data.get('data', [])
                            # Ensure data_list is a list (handle case where JSON has "data": null)
                            if not isinstance(data_list, list):
                                data_list = []
                            for node in data_list:
                                if node and isinstance(node, dict):
                                    if node.get('prefix', '').upper() == hex_prefix:
                                        reserved_nodes.append(node)
                except Exception as e:
                    logger.debug(f"Error reading reserved nodes file: {e}")

            # Build response message
            message_parts = []

            if active_nodes or reserved_nodes:
                # List active nodes
                if active_nodes:
                    # Prefix is in use or reserved
                    message_parts.append(f"{CROSS} {hex_prefix} is **NOT AVAILABLE**\n")
                    message_parts.append(f"Active Repeater(s):")
                    for i, repeater in enumerate(active_nodes, 1):
                        if isinstance(repeater, dict):
                            name = repeater.get('name', 'Unknown')
                            message_parts.append(f"{name}")
                        else:
                            message_parts.append(f"(data error)")

                # List reserved nodes
                if reserved_nodes:
                    # Prefix is in use or reserved
                    message_parts.append(f"{CROSS} {hex_prefix} is **NOT AVAILABLE**\n")
                    message_parts.append(f"Reserved:")
                    for i, node in enumerate(reserved_nodes, 1):
                        name = node.get('name', 'Unknown')
                        display_name = node.get('display_name', node.get('username', 'Unknown'))
                        message_parts.append(f"{name} (reserved by {display_name})")

                # Summary
                # Ensure both are lists (defensive check)
                active_count = len(active_nodes) if active_nodes else 0
                reserved_count = len(reserved_nodes) if reserved_nodes else 0
                total = active_count + reserved_count
                if total == 0:
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
            # Check if hex parameter was provided
            if self.text is None:
                await ctx.respond("Please provide a hex prefix (e.g., `/stats A1`)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/stats A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get repeaters (now returns a list)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=self.days)

            # Filter out removed nodes (category-specific)
            if repeaters and isinstance(repeaters, list):
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
            else:
                repeaters = []

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
                # No active repeater found - check if it's reserved
                reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
                reserved_node = None

                if os.path.exists(reserved_nodes_file):
                    try:
                        with open(reserved_nodes_file, 'r') as f:
                            reserved_data = json.load(f)
                            if reserved_data and isinstance(reserved_data, dict):
                                data_list = reserved_data.get('data', [])
                                # Ensure data_list is a list (handle case where JSON has "data": null)
                                if not isinstance(data_list, list):
                                    data_list = []
                                for node in data_list:
                                    if node and isinstance(node, dict):
                                        if node.get('prefix', '').upper() == hex_prefix:
                                            reserved_node = node
                                            break
                    except Exception as e:
                        logger.debug(f"Error reading reserved nodes file: {e}")

                if reserved_node:
                    # Show reserved listing
                    name = reserved_node.get('name', 'Unknown')
                    display_name = reserved_node.get('display_name', reserved_node.get('username', 'Unknown'))
                    reserved_by = reserved_node.get('reserved_by', 'Unknown')
                    timestamp = reserved_node.get('timestamp', 'Unknown')

                    # Format timestamp if available
                    formatted_timestamp = "Unknown"
                    if timestamp != 'Unknown':
                        try:
                            timestamp_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            formatted_timestamp = timestamp_dt.strftime("%B %d, %Y %I:%M %p")
                        except Exception:
                            formatted_timestamp = timestamp

                    message = f"{RESERVED} Repeater {hex_prefix} is **RESERVED**\n"
                    message += f"Name: {name}\n"
                    message += f"Reserved by: {display_name}\n"
                    if formatted_timestamp != 'Unknown':
                        message += f"Reserved on: {formatted_timestamp}\n"
                else:
                    message = f"No repeater found with prefix {hex_prefix}."

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await ctx.respond("Error retrieving repeater stats.", flags=hikari.MessageFlag.EPHEMERAL)
