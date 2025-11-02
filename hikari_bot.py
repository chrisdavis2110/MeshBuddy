#!/usr/bin/python

import hikari
import lightbulb
import logging
import asyncio
import json
import os
from datetime import datetime
from meshmqtt import MeshMQTTBridge
from helpers import extract_device_types, load_config

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
bridge = MeshMQTTBridge()

EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
pending_remove_selections = {}

def get_removed_nodes_set():
    """Load removedNodes.json and return a set of (prefix, name) tuples for quick lookup"""
    removed_set = set()
    removed_nodes_file = "removedNodes.json"
    if os.path.exists(removed_nodes_file):
        try:
            with open(removed_nodes_file, 'r') as f:
                removed_data = json.load(f)
                for node in removed_data.get('data', []):
                    node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                    node_name = node.get('name', '').strip()
                    if node_prefix and node_name:
                        removed_set.add((node_prefix, node_name))
        except Exception as e:
            logger.debug(f"Error reading removedNodes.json: {e}")
    return removed_set

def is_node_removed(contact):
    """Check if a contact node has been removed"""
    removed_set = get_removed_nodes_set()
    prefix = contact.get('public_key', '')[:2].upper() if contact.get('public_key') else ''
    name = contact.get('name', '').strip()
    return (prefix, name) in removed_set

async def process_repeater_removal(selected_repeater, ctx_or_interaction):
    """Process the removal of a repeater to removedNodes.json"""
    try:
        # Load or create removedNodes.json
        removed_nodes_file = "removedNodes.json"
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
        selected_prefix = selected_repeater.get('public_key', '')[:2].upper() if selected_repeater.get('public_key') else ''
        selected_name = selected_repeater.get('name', '').strip()

        already_removed = False
        for removed_node in removed_data.get('data', []):
            removed_prefix = removed_node.get('public_key', '')[:2].upper() if removed_node.get('public_key') else ''
            removed_name = removed_node.get('name', '').strip()
            if removed_prefix == selected_prefix and removed_name == selected_name:
                already_removed = True
                break

        if already_removed:
            message = f"⚠️ Repeater {selected_prefix}: {selected_name} has already been removed"
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

        message = f"✅ Repeater {selected_prefix}: {selected_name} has been removed"

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
        error_message = f"❌ Error removing repeater: {str(e)}"
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
    """Extract prefix from line for sorting (e.g., '🔴 A1: Name' -> 'A1')"""
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
    """Update Discord channel name with device counts"""
    try:
        # Get channel ID from config (you'll need to add this to config.ini)
        channel_id = config.get("discord", "repeater_channel_id", fallback=None)
        if not channel_id:
            logger.warning("No channel_id specified in config.ini - skipping channel name update")
            return

        # Get device counts
        data = bridge.load_data_from_json()
        devices = extract_device_types(data, ['repeaters'], days=7)

        if devices is None:
            logger.warning("Could not get device data - skipping channel name update")
            return

        repeaters = devices.get('repeaters', [])
        repeaters = [r for r in repeaters if not is_node_removed(r)]
        repeater_count = len(repeaters)

        # Format channel name with count
        channel_name = f"Total Repeaters: {repeater_count}"

        # Update channel name
        await bot.rest.edit_channel(int(channel_id), name=channel_name)
        logger.info(f"Updated channel name to: {channel_name}")

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

async def send_long_message(ctx, header, lines, footer=None, max_length=2000):
    """Send a message that may exceed Discord's character limit by splitting into multiple messages"""
    if not lines:
        message = header
        if footer:
            message += f"\n\n{footer}"
        await ctx.respond(message)
        return

    # Calculate lengths
    header_len = len(header) + 1  # +1 for newline after header
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
            # Use the global bot's REST client to create follow-up messages
            await bot.rest.execute_webhook(
                ctx.interaction.application_id,
                ctx.interaction.token,
                content=message
            )

    # If footer didn't fit in last chunk, send it separately
    if footer and not footer_added:
        if len(footer) <= max_length:
            await bot.rest.execute_webhook(
                ctx.interaction.application_id,
                ctx.interaction.token,
                content=footer
            )

# Start periodic updates when bot starts
@bot.listen()
async def on_starting(event: hikari.StartingEvent):
    """Start periodic channel updates when bot starts"""
    asyncio.create_task(periodic_channel_update())

@client.register()
class ListRepeatersCommand(lightbulb.SlashCommand, name="list",
    description="Get list of active repeaters"):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of active repeaters"""
        try:
            devices = bridge.extract_device_types(device_types=['repeaters'], days=self.days)
            if devices is None:
                await ctx.respond("Error retrieving repeater list.")
                return

            repeaters = devices.get('repeaters', [])
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
                    try:
                        if last_seen:
                            ls = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                            days_ago = (now - ls).days
                            if days_ago > 12:
                                lines.append(f"🔴 {prefix}: {name}") # red
                            elif days_ago > 3:
                                lines.append(f"🟡 {prefix}: {name}") # yellow
                            else:
                                lines.append(f"🟢 {prefix}: {name}")
                    except Exception:
                        pass

            # Add reserved nodes that aren't already active
            if os.path.exists("reservedNodes.json"):
                try:
                    with open("reservedNodes.json", 'r') as f:
                        reserved_data = json.load(f)
                        for node in reserved_data.get('data', []):
                            prefix = node.get('prefix', '').upper()
                            name = node.get('name', 'Unknown')
                            # Only add if not already in active repeaters
                            if prefix and prefix not in active_prefixes:
                                lines.append(f"⏳ {prefix}: {name}")
                except Exception as e:
                    logger.debug(f"Error reading reservedNodes.json: {e}")

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
    description="Get list of offline repeaters"):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of offline repeaters"""
        try:
            devices = bridge.extract_device_types(device_types=['repeaters'], days=self.days)
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
                            if days_ago > 12:
                                lines.append(f"🔴 {prefix}: {name} (last seen: {days_ago} days ago)") # red
                            elif days_ago > 3:
                                lines.append(f"🟡 {prefix}: {name} (last seen: {days_ago} days ago)") # yellow
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
    description="Get list of unused hex keys"):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of unused hex keys"""
        try:
            unused_keys = bridge.get_unused_keys(days=self.days)
            if unused_keys:
                # Remove prefixes from reservedNodes.json (reserved list)
                if os.path.exists("reservedNodes.json"):
                    try:
                        with open("reservedNodes.json", 'r') as f:
                            reserved_data = json.load(f)
                            for node in reserved_data.get('data', []):
                                prefix = node.get('prefix', '').upper()
                                if prefix in unused_keys:
                                    unused_keys.remove(prefix)
                    except Exception as e:
                        logger.debug(f"Error reading reservedNodes.json: {e}")

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
    description="Get list of duplicate repeater prefixes"):

    days = lightbulb.number('days', 'Days to check (default: 7)', default=7)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Get list of duplicate repeater prefixes"""
        try:
            devices = bridge.extract_device_types(device_types=['repeaters'], days=self.days)
            if devices is None:
                await ctx.respond("Error retrieving duplicate prefixes.")
                return

            repeaters = devices.get('repeaters', [])
            repeaters = [r for r in repeaters if not is_node_removed(r)]
            if repeaters:
                # Group repeaters by prefix
                by_prefix = {}
                for c in repeaters:
                    p = (c.get('public_key', '')[:2] if c.get('public_key') else '??')
                    by_prefix.setdefault(p, []).append(c)

                lines = []
                now = datetime.now().astimezone()
                for prefix, group in sorted(by_prefix.items()):
                    names = {c.get('name', 'Unknown') for c in group}
                    if len(group) > 1 and len(names) > 1:
                        for c in group:
                            name = c.get('name', 'Unknown')
                            last_seen = c.get('last_seen')
                            try:
                                if last_seen:
                                    ls = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
                                    days_ago = (now - ls).days
                                    if days_ago > 12:
                                        lines.append(f"🔴 {prefix}: {name}") # red
                                    elif days_ago > 3:
                                        lines.append(f"🟡 {prefix}: {name}") # yellow
                                    else:
                                        lines.append(f"🟢 {prefix}: {name}")
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
    description="Check if a hex prefix is available"):

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

            # Check reservedNodes.json first
            if os.path.exists("reservedNodes.json"):
                try:
                    with open("reservedNodes.json", 'r') as f:
                        reserved_data = json.load(f)
                        for node in reserved_data.get('data', []):
                            if node.get('prefix', '').upper() == hex_prefix:
                                message = f"⏳ {hex_prefix} is on the **RESERVED LIST**"
                                await ctx.respond(message)
                                return
                except Exception as e:
                    logger.debug(f"Error reading reservedNodes.json: {e}")

            # Get unused keys
            unused_keys = bridge.get_unused_keys(days=self.days)

            if unused_keys and hex_prefix in unused_keys:
                message = f"✅ {hex_prefix} is **AVAILABLE** for use!"
            else:
                # Get repeater information for the prefix
                repeaters = bridge.get_repeater(hex_prefix, days=self.days)

                # Filter out removed nodes
                if repeaters:
                    repeaters = [r for r in repeaters if not is_node_removed(r)]

                if repeaters and len(repeaters) > 0:
                    repeater = repeaters[0]  # Get the first repeater
                    if not isinstance(repeater, dict):
                        message = f"❌ {hex_prefix} is **NOT AVAILABLE** (data error)"
                    else:
                        name = repeater.get('name', 'Unknown')
                        last_seen = repeater.get('last_seen', 'Unknown')
                        location = repeater.get('location', {'latitude': 0, 'longitude': 0}) or {'latitude': 0, 'longitude': 0}
                        lat = location.get('latitude', 0)
                        lon = location.get('longitude', 0)

                        # Format last_seen timestamp
                        formatted_last_seen = "Unknown"
                        if last_seen != 'Unknown':
                            try:
                                last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                                formatted_last_seen = last_seen_dt.strftime("%B %d, %Y %I:%M %p")
                            except Exception:
                                formatted_last_seen = "Invalid timestamp"

                        message = f"❌ {hex_prefix} is **NOT AVAILABLE**\n\n**Current User:**\n"
                        message += f" Name: {name}\n"
                        message += f" Last Seen: {formatted_last_seen}\n"
                        message += f" Location: {lat}, {lon}"

                        if len(repeaters) > 1:
                            message += f"\n\n*Note: {len(repeaters)} repeater(s) found with this prefix*"
                else:
                    message = f"❌ {hex_prefix} is **NOT AVAILABLE** (already in use)"

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in prefix command: {e}")
            await ctx.respond("Error checking prefix availability.")


@client.register()
class RepeaterStatsCommand(lightbulb.SlashCommand, name="stats",
    description="Get the stats of a repeater"):

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
            repeaters = bridge.get_repeater(hex_prefix, days=self.days)

            # Filter out removed nodes
            if repeaters:
                repeaters = [r for r in repeaters if not is_node_removed(r)]

            if repeaters and len(repeaters) > 0:
                if len(repeaters) == 1:
                    # Single repeater - show detailed info
                    repeater = repeaters[0]
                    if not isinstance(repeater, dict):
                        await ctx.respond(f"Error: Invalid repeater data")
                        return

                    name = repeater.get('name', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')
                    location = repeater.get('location', {'latitude': 0, 'longitude': 0}) or {'latitude': 0, 'longitude': 0}
                    lat = location.get('latitude', 0)
                    lon = location.get('longitude', 0)

                    # Format last_seen timestamp
                    formatted_last_seen = "Unknown"
                    if last_seen != 'Unknown':
                        try:
                            last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                            formatted_last_seen = last_seen_dt.strftime("%B %d, %Y %I:%M %p")
                        except Exception:
                            formatted_last_seen = "Invalid timestamp"

                    message = f"Repeater {hex_prefix}:\n Name: {name}\n Last Seen: {formatted_last_seen}\n Location: {lat}, {lon}"
                else:
                    # Multiple repeaters - show summary
                    message = f"Found {len(repeaters)} repeater(s) with prefix {hex_prefix}:\n\n"
                    for i, repeater in enumerate(repeaters, 1):
                        if not isinstance(repeater, dict):
                            continue

                        name = repeater.get('name', 'Unknown')
                        last_seen = repeater.get('last_seen', 'Unknown')
                        location = repeater.get('location', {'latitude': 0, 'longitude': 0}) or {'latitude': 0, 'longitude': 0}
                        lat = location.get('latitude', 0)
                        lon = location.get('longitude', 0)

                        # Format last_seen timestamp
                        formatted_last_seen = "Unknown"
                        if last_seen != 'Unknown':
                            try:
                                last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                                formatted_last_seen = last_seen_dt.strftime("%B %d, %Y %I:%M %p")
                            except Exception:
                                formatted_last_seen = "Invalid timestamp"

                        message += f"**#{i}:** {name}\n Last Seen: {formatted_last_seen}\n Location: {lat}, {lon}\n\n"
            else:
                message = f"No repeater found with prefix {hex_prefix}."

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await ctx.respond("Error retrieving repeater stats.")


@client.register()
class ReserveRepeaterCommand(lightbulb.SlashCommand, name="reserve",
    description="Reserve a hex prefix for a repeater"):

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

            # Load existing reservedNodes.json or create new structure
            reserved_nodes_file = "reservedNodes.json"
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
                await ctx.respond(f"❌ {hex_prefix} with name: **{name}** has already been reserved")
                return

            # Check if prefix is currently in use by an active repeater
            unused_keys = bridge.get_unused_keys(days=7)
            if unused_keys is None:
                await ctx.respond("❌ Error: Could not check prefix availability. Please try again.")
                return

            # Check if prefix is in unused keys (available for reservation)
            if hex_prefix not in unused_keys:
                # Prefix is currently in use - get repeater info to show who's using it
                repeaters = bridge.get_repeater(hex_prefix, days=7)
                if repeaters:
                    # Filter out removed nodes
                    repeaters = [r for r in repeaters if not is_node_removed(r)]
                    if repeaters:
                        repeater = repeaters[0]
                        current_name = repeater.get('name', 'Unknown')
                        await ctx.respond(
                            f"❌ Prefix {hex_prefix} is **NOT AVAILABLE** - currently in use by: **{current_name}**\n"
                            f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                        )
                        return

                # Prefix not in unused keys but no active repeater found (edge case)
                await ctx.respond(
                    f"❌ Prefix {hex_prefix} is **NOT AVAILABLE** for reservation.\n"
                    f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                )
                return
            # Create node entry
            node_entry = {
                "prefix": hex_prefix,
                "name": name,
                "added_at": datetime.now().isoformat()
            }

            # Add new entry
            reserved_data['data'].append(node_entry)
            message = f"✅ Reserved hex prefix {hex_prefix} for repeater: **{name}**"

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in reserve command: {e}")
            await ctx.respond(f"❌ Error reserving hex prefix for repeater: {str(e)}")


@client.register()
class ReleaseRepeaterCommand(lightbulb.SlashCommand, name="release",
    description="Release a hex prefix for a repeater"):

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

            # Load existing customNodes.json
            reserved_nodes_file = "reservedNodes.json"
            if not os.path.exists(reserved_nodes_file):
                await ctx.respond(f"Error: list does not exist)")
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
                await ctx.respond(f"❌ {hex_prefix} is not reserved for a repeater")
                return

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            message = f"✅ Released hex prefix {hex_prefix}"
            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in release command: {e}")
            await ctx.respond(f"Error releasing hex prefix: {str(e)}")


@client.register()
class RemoveNodeCommand(lightbulb.SlashCommand, name="remove",
    description="Remove a repeater from the repeater list"):

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

            # Load nodes.json
            nodes_file = "nodes.json"
            if not os.path.exists(nodes_file):
                await ctx.respond("❌ Error: nodes.json not found")
                return

            with open(nodes_file, 'r') as f:
                nodes_data = json.load(f)

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    if not is_node_removed(node):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"❌ No repeater found with hex prefix {hex_prefix}")
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
            await ctx.respond(f"❌ Error removing repeater: {str(e)}")


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
                    "❌ No selection made",
                    components=None
                )


@client.register()
class UpdateChannelCommand(lightbulb.SlashCommand, name="updatechannels",
    description="Manually update the channel name with current device counts"):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Manually update channel names with counts"""
        try:
            await ctx.respond("Updating channel name...")
            await update_repeater_channel_name()
            await ctx.respond("✅ Channel name updated successfully!")
        except Exception as e:
            logger.error(f"Error in updatechannel command: {e}")
            await ctx.respond("❌ Error updating channel name.")


@client.register()
class HelpCommand(lightbulb.SlashCommand, name="help",
    description="Show all available commands"):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Show all available commands"""
        try:
            help_message = """**Available Bot Commands:**

`/list` - Get list of active repeaters*
`/offline` - Get list of offline repeaters (>3 days no advert)*
`/open` - Get list of unused hex keys*
`/dupes` - Get list of duplicate repeater prefixes*
`/prefix <hex>` - Check if a hex prefix is available*
`/stats <hex>` - Get detailed stats of a repeater by hex prefix*
`/reserve <prefix> <name>` - Reserve a hex prefix for a repeater
`/release <prefix>` - Release a hex prefix from the reserve list
`/remove <hex>` - Remove a repeater from the repeater list
`/help` - Show this help message

**Commands also accept an optional `days` parameter (default: 7 days)*"""

            await ctx.respond(help_message)
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.respond("Error retrieving help information.")

if __name__ == "__main__":
    bot.run()