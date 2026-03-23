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
    get_unused_keys_for_1byte,
    get_unused_keys_with_prefix,
    get_used_full_prefixes_for_context,
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
                    prefix_length = await get_prefix_length_for_context(ctx)
                    with open(removed_nodes_file, 'r') as f:
                        removed_data = json.load(f)
                        for node in removed_data.get('data', []):
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

    hex_char = lightbulb.string('hex', 'Hex prefix', default=None)
    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of unused hex keys"""
        open_deferred = False
        try:
            # No hex provided: only use get_unused_keys_for_1byte
            if self.hex_char is None:
                # Defer before channel fetch + file scan — both can approach Discord's ~3s interaction limit.
                await ctx.defer()
                open_deferred = True
                prefix_length = await get_prefix_length_for_context(ctx)
                one_byte_list = await get_unused_keys_for_1byte(ctx, days=self.days)
                if one_byte_list is None:
                    await ctx.interaction.edit_initial_response("Error retrieving unused keys.")
                    return
                if not one_byte_list:
                    if prefix_length >= 4:
                        await ctx.interaction.edit_initial_response(
                            "All 256 1-byte prefixes are currently in use. Use `/open <hex>` to see keys under a prefix."
                        )
                    else:
                        await ctx.interaction.edit_initial_response("All 256 prefixes are currently in use!")
                    return
                grouped_by_tens = {}
                for byte in one_byte_list:
                    tens = byte[0].upper()
                    grouped_by_tens.setdefault(tens, []).append(byte)
                lines = []
                key_width = 2
                for tens in sorted(grouped_by_tens.keys(), key=lambda c: int(c, 16)):
                    bytes_in_group = sorted(grouped_by_tens[tens], key=lambda x: int(x, 16))
                    lines.append(" ".join(f"{b:>{key_width}}" for b in bytes_in_group))
                if prefix_length >= 4:
                    header = "Available 1-byte prefixes:"
                    footer = f"Total: {len(one_byte_list)} 1-byte prefix(es). Use `/open <hex>` to see keys under a prefix."
                else:
                    header = "Available prefixes:"
                    footer = f"Total: {len(one_byte_list)} key(s)"
                await send_long_message(
                    ctx, header, lines, footer, edit_initial_for_first_chunk=True
                )
                return

            prefix_length = await get_prefix_length_for_context(ctx)

            # Hex provided: length must match hash_size (2, 4, or 6 chars)
            hex_char = self.hex_char.upper().strip()
            allowed_lengths = [2]
            if prefix_length >= 4:
                allowed_lengths.append(4)
            if prefix_length >= 6:
                allowed_lengths.append(6)
            if len(hex_char) not in allowed_lengths or not all(c in '0123456789ABCDEF' for c in hex_char):
                hint = f"Use {prefix_length} hex characters for this category (e.g. /open {'XX' * (prefix_length // 2)})"
                await ctx.respond(f"Invalid hex. {hint}", flags=hikari.MessageFlag.EPHEMERAL)
                return
            if hex_char[:2] in {"00", "FF"}:
                await ctx.respond("Prefix cannot start with 00 or FF.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            await ctx.defer()
            open_deferred = True

            filtered_keys = await get_unused_keys_with_prefix(ctx, hex_char, days=self.days)
            if filtered_keys is None:
                await ctx.interaction.edit_initial_response("Error retrieving unused keys.")
                return

            if not filtered_keys:
                await ctx.interaction.edit_initial_response(
                    f"No open keys found starting with '{hex_char}'."
                )
                return

            prefix_len = len(hex_char)
            # Full key: prefix length equals category prefix length → show single key
            if prefix_len == prefix_length:
                lines = [hex_char]
                header = f"Unused keys starting with '{hex_char}':"
                footer = "Total: 1 key"
                await send_long_message(
                    ctx, header, lines, footer, edit_initial_for_first_chunk=True
                )
                return

            # Next-byte columns with *no* repeater in that column (distinct count drops when any key uses prefix+BB)
            used_prefixes, _plen = await get_used_full_prefixes_for_context(ctx, days=self.days)
            if used_prefixes is None:
                await ctx.interaction.edit_initial_response("Error retrieving used keys.")
                return
            fully_open_next = []
            for i in range(256):
                bb = f"{i:02X}"
                col = hex_char + bb
                if not any(uk.startswith(col) for uk in used_prefixes):
                    fully_open_next.append(bb)
            if not fully_open_next and filtered_keys:
                await ctx.interaction.edit_initial_response(
                    f"No next-byte column is completely repeater-free under `{hex_char}`. "
                    f"Use a longer prefix (e.g. `/open {hex_char}XX`) to list keys where repeaters exist."
                )
                return
            grouped_by_tens = {}
            for byte in fully_open_next:
                tens = byte[0].upper()
                grouped_by_tens.setdefault(tens, []).append(byte)
            lines = []
            key_width = 2
            for tens in sorted(grouped_by_tens.keys(), key=lambda c: int(c, 16)):
                bytes_in_group = sorted(grouped_by_tens[tens], key=lambda x: int(x, 16))
                lines.append(" ".join(f"{b:>{key_width}}" for b in bytes_in_group))
            header = f"Unused keys starting with '{hex_char}':"
            footer = f"Total: {len(fully_open_next)} keys"
            if len(hex_char) == 2:
                footer += f". Use `/open {hex_char}XX` to see remaining keys under that prefix."
            await send_long_message(
                ctx, header, lines, footer, edit_initial_for_first_chunk=True
            )
        except Exception as e:
            logger.error(f"Error in open command: {e}")
            try:
                if open_deferred:
                    await ctx.interaction.edit_initial_response("Error retrieving unused keys.")
                else:
                    await ctx.respond(
                        "Error retrieving unused keys.",
                        flags=hikari.MessageFlag.EPHEMERAL,
                    )
            except Exception:
                logger.debug("Could not send open command error response", exc_info=True)
