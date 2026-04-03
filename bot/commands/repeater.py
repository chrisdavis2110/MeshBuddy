"""
Repeater Commands

Commands for viewing and querying repeater information:
- prefix: Check if a hex prefix is available
- stats: Get detailed stats of a repeater by hex prefix
- phash: Count repeaters by public-key hash size (1–3 bytes), or list repeaters for a given size
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
    get_prefix_length_for_context,
    normalize_node,
    is_node_removed,
    validate_hex_prefix_for_category,
    extract_prefix_for_sort,
)
from bot.tasks import send_long_message


def _repeater_hash_mode_bytes(contact: dict) -> int | None:
    """Return clamped hash size in bytes (1–3) from node hash_mode, or None if missing/invalid."""
    hm = contact.get("hash_mode")
    if hm is None:
        return None
    if hasattr(hm, "value"):
        hm = hm.value
    try:
        n = int(hm)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return 1
    if n > 3:
        return 3
    return n


@client.register()
class CheckPrefixCommand(lightbulb.SlashCommand, name="prefix",
    description="Check if a hex prefix is available", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix')
    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Check if a hex prefix is available and list all nodes with that prefix"""
        try:

            # Check if hex parameter was provided
            if self.text is None:
                await ctx.respond("Please provide a hex prefix (e.g., `/prefix A1` or `/prefix A1B2`)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            prefix_length = await get_prefix_length_for_context(ctx)
            ok, hex_prefix_or_err = validate_hex_prefix_for_category(self.text, prefix_length)
            if not ok:
                await ctx.respond(hex_prefix_or_err, flags=hikari.MessageFlag.EPHEMERAL)
                return
            hex_prefix = hex_prefix_or_err

            # Collect all nodes with this prefix
            active_nodes = []
            reserved_nodes = []
            plen = len(hex_prefix)

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
                        normalize_node(contact)
                        if contact.get('device_role') == 2:
                            pk = (contact.get('public_key') or '').upper()
                            if len(pk) >= plen and pk[:plen] == hex_prefix:
                                repeaters.append(contact)

                    # Filter out removed nodes (category-specific)
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
                                    node_prefix = (node.get('prefix') or '').upper()
                                    # Reserved nodes store full prefix (2, 4, or 6 chars); match if it starts with hex_prefix
                                    if len(node_prefix) >= plen and node_prefix[:plen] == hex_prefix:
                                        reserved_nodes.append(node)
                except Exception as e:
                    logger.debug(f"Error reading reserved nodes file: {e}")

            # Build response message
            message_parts = []

            if active_nodes or reserved_nodes:
                message_parts.append(f"{CROSS} {hex_prefix} is **NOT AVAILABLE**\n")
                # List active nodes
                if active_nodes:
                    # Prefix is in use or reserved
                    message_parts.append(f"Active Repeater(s):")
                    for i, repeater in enumerate(active_nodes, 1):
                        if isinstance(repeater, dict):
                            name = repeater.get('name', 'Unknown')
                            pk = (repeater.get('public_key') or '').upper()
                            key_hex = (
                                pk[:prefix_length]
                                if len(pk) >= prefix_length
                                else pk or "?"
                            )
                            message_parts.append(f"{key_hex}: {name}")
                        else:
                            message_parts.append(f"(data error)")

                # List reserved nodes
                if reserved_nodes:
                    # Prefix is in use or reserved
                    message_parts.append(f"Reserved:")
                    for i, node in enumerate(reserved_nodes, 1):
                        name = node.get('name', 'Unknown')
                        display_name = node.get('display_name', node.get('username', 'Unknown'))
                        node_prefix = (node.get('prefix') or '').upper()
                        key_hex = (
                            node_prefix[:prefix_length]
                            if len(node_prefix) >= prefix_length
                            else node_prefix or "?"
                        )
                        message_parts.append(
                            f"{key_hex}: {name} (reserved by {display_name})"
                        )

                # Summary
                # Ensure both are lists (defensive check)
                active_count = len(active_nodes) if active_nodes else 0
                reserved_count = len(reserved_nodes) if reserved_nodes else 0
                total = active_count + reserved_count
                if total == 0:
                    message_parts.append(f"\n{CHECK} {hex_prefix} is **AVAILABLE** for use!")
            else:
                # Check availability: full prefix must be in unused_keys; 2-char is available if any full prefix under it is unused
                unused_keys = await get_unused_keys_for_context(ctx, days=self.days)
                if unused_keys:
                    if len(hex_prefix) == prefix_length:
                        available = hex_prefix in unused_keys
                    else:
                        available = any(k.startswith(hex_prefix) for k in unused_keys)
                else:
                    available = False
                if available:
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

    text = lightbulb.string('hex', 'Hex prefix')
    days = lightbulb.number('days', 'Days to check (default: 14)', default=14)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get the stats of a repeater"""
        try:
            # Check if hex parameter was provided
            if self.text is None:
                await ctx.respond("Please provide a hex prefix (e.g., `/stats A1` or `/stats A1B2`)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            prefix_length = await get_prefix_length_for_context(ctx)
            ok, hex_prefix_or_err = validate_hex_prefix_for_category(self.text, prefix_length)
            if not ok:
                await ctx.respond(hex_prefix_or_err, flags=hikari.MessageFlag.EPHEMERAL)
                return
            hex_prefix = hex_prefix_or_err
            plen = len(hex_prefix)

            # Load all repeaters (not filtered by days) to include future timestamps
            data = await get_nodes_data_for_context(ctx)
            if data is None:
                await ctx.respond("Error retrieving repeater stats.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            contacts = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(contacts, list):
                await ctx.respond("Error retrieving repeater stats.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Filter to repeaters with matching prefix
            repeaters = []
            for contact in contacts:
                if not isinstance(contact, dict):
                    continue
                normalize_node(contact)
                if contact.get('device_role') == 2:
                    pk = (contact.get('public_key') or '').upper()
                    if len(pk) >= plen and pk[:plen] == hex_prefix:
                        repeaters.append(contact)

            # Filter out removed nodes (category-specific)
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
                    pk_u = (public_key or "").strip().upper() if isinstance(public_key, str) else ""
                    display_prefix = (
                        pk_u[:prefix_length] if len(pk_u) >= prefix_length else hex_prefix
                    )
                    last_seen = repeater.get('last_seen', 'Unknown')
                    location = repeater.get('location', {'latitude': 0, 'longitude': 0}) or {'latitude': 0, 'longitude': 0}
                    lat = location.get('latitude', 0)
                    lon = location.get('longitude', 0)
                    battery = repeater.get('battery_voltage', 0)
                    hash_mode = repeater.get('hash_mode')

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

                    message = f"Repeater {display_prefix}:\nName: {name}\nKey: {public_key}\nLast Seen: {formatted_last_seen}\nLocation: {lat}, {lon}\n"

                    if hash_mode is not None:
                        message += f"Hash size: {hash_mode}-byte \n"

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
                        hash_mode = repeater.get('hash_mode')

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

                        if hash_mode is not None:
                            message += f"Hash size: {hash_mode}-byte\n"

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
                                        node_prefix = (node.get('prefix') or '').upper()
                                        if len(node_prefix) >= plen and node_prefix[:plen] == hex_prefix:
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


@client.register()
class PhashCommand(lightbulb.SlashCommand, name="phash",
    description="List repeaters by hash size",
    hooks=[category_check]):

    hash_size = lightbulb.integer(
        "hash_size",
        "Hash size in bytes (1–3)",
        default=None,
        min_value=1,
        max_value=3,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Summarize or list repeaters by hash_mode."""
        try:
            data = await get_nodes_data_for_context(ctx)
            if data is None:
                await ctx.respond("Error loading repeater data.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            contacts = data.get("data", []) if isinstance(data, dict) else data
            if not isinstance(contacts, list):
                await ctx.respond("Error loading repeater data.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            repeaters = []
            for contact in contacts:
                if not isinstance(contact, dict):
                    continue
                normalize_node(contact)
                if contact.get("device_role") == 2:
                    repeaters.append(contact)

            removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
            repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

            if self.hash_size is None:
                c1 = c2 = c3 = c_unknown = 0
                for r in repeaters:
                    hm = _repeater_hash_mode_bytes(r)
                    if hm == 1:
                        c1 += 1
                    elif hm == 2:
                        c2 += 1
                    elif hm == 3:
                        c3 += 1
                    else:
                        c_unknown += 1
                total = len(repeaters)
                msg = (
                    "**Repeaters by hash size**\n"
                    f"1-byte: **{c1}**\n"
                    f"2-byte: **{c2}**\n"
                    f"3-byte: **{c3}**\n"
                )
                if c_unknown:
                    msg += f"No hash size reported: **{c_unknown}**\n"
                msg += f"Total repeaters: **{total}**"
                await ctx.respond(msg)
                return

            hs = int(self.hash_size)
            if hs < 1:
                hs = 1
            elif hs > 3:
                hs = 3

            plen = hs * 2
            matched = []
            for r in repeaters:
                if _repeater_hash_mode_bytes(r) == hs:
                    matched.append(r)

            if not matched:
                await ctx.respond(f"No repeaters with {hs}-byte hash size.")
                return

            lines = []
            for contact in matched:
                pk = (contact.get("public_key") or "").strip().upper()
                prefix = pk[:plen] if len(pk) >= plen else (pk or "????")
                name = contact.get("name", "Unknown")
                lines.append(f"{prefix}: {name}")

            lines.sort(key=extract_prefix_for_sort)
            header = f"Repeaters with {hs}-byte hash size:"
            footer = f"Total: {len(matched)}"
            await send_long_message(ctx, header, lines, footer)
        except Exception as e:
            logger.error(f"Error in phash command: {e}")
            await ctx.respond("Error running /phash.", flags=hikari.MessageFlag.EPHEMERAL)
