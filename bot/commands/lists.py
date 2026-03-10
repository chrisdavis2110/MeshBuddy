"""
List Commands

Commands for viewing and querying lists of repeaters:
- list: Get list of active repeaters
- offline: Get list of offline repeaters
- dupes: Get list of duplicate repeater prefixes
- xlist: Get list of removed repeaters
- rlist: Get list of reserved repeaters
- open: Get list of unused hex keys
"""

import json
import os
from datetime import datetime
import hikari
import lightbulb
from bot.core import client, logger, CHECK, CROSS, WARN, RESERVED, category_check
from bot.utils import (
    get_nodes_data_for_context,
    get_removed_nodes_file_for_context,
    get_reserved_nodes_file_for_context,
    get_extract_device_types_for_context,
    get_unused_keys_for_context,
    get_prefix_length_for_context,
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
            # Load nodes data based on the channel where the command was invoked
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

            # Filter out removed nodes
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

            # Track active repeater prefixes to avoid duplicates
            active_prefixes = set()

            lines = []
            active_repeater_count = 0  # Track count of active repeaters only
            now = datetime.now().astimezone()

            # Add active repeaters
            if repeaters:
                prefix_length = await get_prefix_length_for_context(ctx)
                for contact in repeaters:
                    prefix = contact.get('public_key', '')[:prefix_length] if contact.get('public_key') else '????'
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
            # Filter out removed nodes
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
            if repeaters:
                lines = []
                now = datetime.now().astimezone()
                prefix_length = await get_prefix_length_for_context(ctx)
                for contact in repeaters:
                    prefix = contact.get('public_key', '')[:prefix_length] if contact.get('public_key') else '????'
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
class DuplicateKeysCommand(lightbulb.SlashCommand, name="dupes",
    description="Get list of duplicate repeater prefixes", hooks=[category_check]):

    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of duplicate repeater prefixes"""
        try:
            # Load all repeaters (not filtered by days) to include future timestamps
            data = await get_nodes_data_for_context(ctx)
            if data is None:
                await ctx.respond("Error retrieving duplicate prefixes.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            contacts = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(contacts, list):
                await ctx.respond("Error retrieving duplicate prefixes.", flags=hikari.MessageFlag.EPHEMERAL)
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
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
            if repeaters:
                # Group repeaters by prefix
                by_prefix = {}
                prefix_length = await get_prefix_length_for_context(ctx)
                for repeater in repeaters:
                    public_key = (repeater.get('public_key', '').upper() if repeater.get('public_key') else '')
                    if public_key:
                        prefix = public_key[:prefix_length]
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
                                    if days_ago < 0:
                                        # Future timestamp
                                        days_ahead = abs(days_ago)
                                        lines.append(f"⚪ {prefix}: {name} ({days_ahead} days in future)")
                                    elif days_ago >= 12:
                                        lines.append(f"{CROSS} {prefix}: {name} ({days_ago} days ago)") # red
                                    elif days_ago >= 3:
                                        lines.append(f"{WARN} {prefix}: {name} ({days_ago} days ago)") # yellow
                                    else:
                                        lines.append(f"{CHECK} {prefix}: {name}")
                                else:
                                    # No timestamp
                                    lines.append(f"⚪ {prefix}: {name} (no timestamp)")
                            except Exception:
                                # Invalid timestamp
                                lines.append(f"⚪ {prefix}: {name} (invalid timestamp)")

                if lines:
                    header = "Duplicate Repeater Prefixes:"
                    footer = f"Total Duplicates: {len(lines)}"
                    await send_long_message(ctx, header, lines, footer)
                else:
                    await ctx.respond("No duplicate prefixes found.")
            else:
                await ctx.respond("No duplicate prefixes found.")

        except Exception as e:
            logger.error(f"Error in dupes command: {e}")
            await ctx.respond("Error retrieving duplicate prefixes.", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class ListRemovedCommand(lightbulb.SlashCommand, name="xlist",
    description="Get list of removed repeaters", hooks=[category_check]):

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
                            prefix_length = await get_prefix_length_for_context(ctx)
                            public_key = node.get('public_key', '')[:prefix_length].upper() if node.get('public_key') else ''
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


@client.register()
class ListReservedCommand(lightbulb.SlashCommand, name="rlist",
    description="Get list of reserved repeaters", hooks=[category_check]):

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
class OpenKeysCommand(lightbulb.SlashCommand, name="open",
    description="Get list of unused hex keys", hooks=[category_check]):

    hex_char = lightbulb.string('hex', 'Hex prefix (e.g., A1)', default=None)
    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of unused hex keys"""
        try:
            unused_keys = await get_unused_keys_for_context(ctx, days=self.days)

            if not unused_keys:
                # Determine total keyspace for this category
                prefix_length = await get_prefix_length_for_context(ctx)
                total_keys = 16 ** prefix_length
                low = "0" * prefix_length
                high = "F" * prefix_length
                await ctx.respond(f"All {total_keys} keys ({low}-{high}) are currently in use!")
                return

            # If no hex argument provided, show count and prompt for hex
            if self.hex_char is None:
                count = len(unused_keys)
                await ctx.respond(f"There are **{count}** unused keys. Use `/open <hex>` to see keys starting with that hex byte (00-FF).")
                return

            # Validate hex byte (2 characters)
            hex_char = self.hex_char.upper().strip()
            if len(hex_char) != 2 or not all(c in '0123456789ABCDEF' for c in hex_char):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `/open A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Filter keys that start with the specified hex byte (first 2 characters)
            filtered_keys = [key for key in unused_keys if key.startswith(hex_char)]

            if not filtered_keys:
                await ctx.respond(f"No open keys found starting with '{hex_char}'.")
                return

            # Sort the filtered keys numerically
            filtered_keys.sort(key=lambda x: int(x, 16))

            # Group keys by the first character of the second byte (3rd character overall)
            grouped_keys = {}
            for key in filtered_keys:
                third_char = key[2] if len(key) >= 3 else ''  # First char of second byte
                if third_char not in grouped_keys:
                    grouped_keys[third_char] = []
                grouped_keys[third_char].append(key)

            # Format keys, breaking long lines into chunks to fit Discord's 2000 char limit
            lines = []
            max_line_length = 1800  # Leave room for header/footer

            # Process each group (each group starts a new line)
            for third_char in sorted(grouped_keys.keys()):
                keys_in_group = grouped_keys[third_char]

                # Build line in chunks to avoid exceeding Discord's limit
                current_line = []

                for key in keys_in_group:
                    key_str = f"{key:>4}"

                    # Calculate what the line would look like with this key added
                    test_line = current_line + [key_str]
                    test_line_str = " ".join(test_line)

                    # Check if adding this key would exceed the limit
                    if current_line and len(test_line_str) > max_line_length:
                        # Save current line and start a new one
                        lines.append(" ".join(current_line))
                        current_line = [key_str]
                    else:
                        # Add to current line
                        current_line.append(key_str)

                # Add any remaining keys as a line
                if current_line:
                    lines.append(" ".join(current_line))

            header = f"Unused Keys starting with '{hex_char}':"
            footer = f"Total: {len(filtered_keys)} keys"
            await send_long_message(ctx, header, lines, footer)
        except Exception as e:
            logger.error(f"Error in open command: {e}")
            await ctx.respond("Error retrieving unused keys.", flags=hikari.MessageFlag.EPHEMERAL)
