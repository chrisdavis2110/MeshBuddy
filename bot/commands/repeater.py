"""
Repeater Commands

Commands for viewing and querying repeater information:
- prefix: Check if a hex prefix is available
- stats: Get detailed stats of a repeater by hex prefix
"""

import json
import os
from datetime import datetime
import hikari
import lightbulb
from bot.core import client, logger, CHECK, CROSS, RESERVED, category_check
from bot.utils import (
    get_nodes_data_for_context,
    get_removed_nodes_file_for_context,
    get_reserved_nodes_file_for_context,
    get_unused_keys_for_context,
    normalize_node,
    is_node_removed,
)


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

            # Load all repeaters (not filtered by days) to include future timestamps
            data = await get_nodes_data_for_context(ctx)
            if data is not None:
                contacts = data.get("data", []) if isinstance(data, dict) else data
                if isinstance(contacts, list):
                    # Filter to repeaters with matching prefix and normalize field names
                    repeaters = []
                    for contact in contacts:
                        if not isinstance(contact, dict):
                            continue
                        # Normalize field names
                        normalize_node(contact)
                        # Only include repeaters (device_role == 2) with matching prefix
                        if contact.get('device_role') == 2:
                            contact_prefix = contact.get('public_key', '')[:2].upper() if contact.get('public_key') else ''
                            if contact_prefix == hex_prefix:
                                repeaters.append(contact)

                    # Filter out removed nodes
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    active_nodes = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

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

            # Load all repeaters (not filtered by days) to include future timestamps
            data = await get_nodes_data_for_context(ctx)
            if data is None:
                await ctx.respond("Error retrieving repeater stats.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            contacts = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(contacts, list):
                await ctx.respond("Error retrieving repeater stats.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Filter to repeaters with matching prefix and normalize field names
            repeaters = []
            for contact in contacts:
                if not isinstance(contact, dict):
                    continue
                # Normalize field names
                normalize_node(contact)
                # Only include repeaters (device_role == 2) with matching prefix
                if contact.get('device_role') == 2:
                    contact_prefix = contact.get('public_key', '')[:2].upper() if contact.get('public_key') else ''
                    if contact_prefix == hex_prefix:
                        repeaters.append(contact)

            # Filter out removed nodes
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

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
                    if last_seen and last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                            now = datetime.now(last_seen_dt.tzinfo)
                            days_diff = (last_seen_dt - now).days
                            if days_diff > 0:
                                # Future timestamp
                                formatted_last_seen = f"{last_seen_dt.strftime('%B %d, %Y %I:%M %p')} ({days_diff} days in future)"
                            else:
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
                        if last_seen and last_seen != 'Unknown':
                            try:
                                last_seen_dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                                now = datetime.now(last_seen_dt.tzinfo)
                                days_diff = (last_seen_dt - now).days
                                if days_diff > 0:
                                    # Future timestamp
                                    formatted_last_seen = f"{last_seen_dt.strftime('%B %d, %Y %I:%M %p')} ({days_diff} days in future)"
                                else:
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
