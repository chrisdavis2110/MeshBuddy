#!/usr/bin/python

import hikari
import lightbulb
import configparser
import logging
import sys
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

        repeater_count = len(devices.get('repeaters', []))

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
            # Update every 5 minutes (300 seconds)
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Error in periodic channel update: {e}")
            # Wait 60 seconds before retrying on error
            await asyncio.sleep(60)

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
            repeater_list = bridge.get_repeater_list(days=self.days)
            if repeater_list:
                message = "Active Repeaters:\n" + "\n".join(repeater_list) + "\n\n" + "Total Repeaters: " + str(len(repeater_list))
            else:
                message = "No active repeaters found."

            await ctx.respond(message)
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
            repeater_list = bridge.get_repeater_offline(days=self.days)
            if repeater_list:
                message = "Offline Repeaters:\n" + "\n".join(repeater_list) + "\n\n" + "Total Repeaters: " + str(len(repeater_list))
            else:
                message = "No offline repeaters found."

            await ctx.respond(message)
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
                # Check customNodes.json first
                custom_name = None
                if os.path.exists("customNodes.json"):
                    try:
                        with open("customNodes.json", 'r') as f:
                            custom_data = json.load(f)
                            for node in custom_data.get('data', []):
                                if node.get('prefix', '').upper() in unused_keys:
                                    unused_keys.remove(node.get('prefix', '').upper())
                    except Exception as e:
                        logger.debug(f"Error reading customNodes.json: {e}")

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
            duplicate_list = bridge.get_repeater_duplicates(days=self.days)
            if duplicate_list:
                message = "Duplicate Repeater Prefixes:\n" + "\n".join(duplicate_list)
            else:
                message = "No duplicate prefixes found."

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in dupes command: {e}")
            await ctx.respond("Error retrieving duplicate prefixes.")


@client.register()
class CheckPrefixCommand(lightbulb.SlashCommand, name="prefix",
    description="Check if a hex prefix is available"):

    text = lightbulb.string('hex', 'Hex prefix to check (e.g., A1)')
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

            # Check customNodes.json first
            custom_name = None
            if os.path.exists("customNodes.json"):
                try:
                    with open("customNodes.json", 'r') as f:
                        custom_data = json.load(f)
                        for node in custom_data.get('data', []):
                            if node.get('prefix', '').upper() == hex_prefix:
                                custom_name = node.get('name', 'Unknown')
                                message = f"⏳ {hex_prefix} is in the **WAITING LIST**\n\n**Repeater Name:** {custom_name}\n*This prefix has been reserved*"
                                await ctx.respond(message)
                                return
                except Exception as e:
                    logger.debug(f"Error reading customNodes.json: {e}")

            # Get unused keys
            unused_keys = bridge.get_unused_keys(days=self.days)

            if unused_keys and hex_prefix in unused_keys:
                message = f"✅ {hex_prefix} is **AVAILABLE** for use!"
            else:
                # Get repeater information for the prefix
                repeaters = bridge.get_repeater(hex_prefix, days=self.days)

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

    text = lightbulb.string('hex', 'Hex prefix of repeater (e.g., A1)')
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

    prefix = lightbulb.string('prefix', 'Hex prefix (e.g., A1)')
    name = lightbulb.string('name', 'Repeater name')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Reserve a hex prefix for a repeater"""
        try:
            prefix = self.prefix.upper().strip()

            # Validate hex format
            if len(prefix) != 2 or not all(c in '0123456789ABCDEF' for c in prefix):
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
                if node.get('prefix', '').upper() == prefix:
                    existing_node = node
                    break

            # Create node entry
            node_entry = {
                "prefix": prefix,
                "name": name,
                "added_at": datetime.now().isoformat()
            }

            if existing_node:
                # Update existing entry
                existing_node['name'] = name
                existing_node['updated_at'] = datetime.now().isoformat()
                message = f"✅ Updated repeater {prefix} with name: **{name}**"
            else:
                # Add new entry
                reserved_data['data'].append(node_entry)
                message = f"✅ Reserved hex prefix {prefix} for repeater: **{name}**"

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

    prefix = lightbulb.string('prefix', 'Hex prefix to remove (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Release a hex prefix for a repeater"""
        try:
            prefix = self.prefix.upper().strip()

            # Validate hex format
            if len(prefix) != 2 or not all(c in '0123456789ABCDEF' for c in prefix):
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
                if node.get('prefix', '').upper() != prefix
            ]
            removed_count = initial_count - len(reserved_data['data'])

            if removed_count == 0:
                await ctx.respond(f"❌ {prefix} is not reserved for a repeater")
                return

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            message = f"✅ Released hex prefix {prefix}"
            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in release command: {e}")
            await ctx.respond(f"Error releasing hex prefix: {str(e)}")


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

`/list` - Get list of active repeaters
`/offline` - Get list of offline repeaters (>2 days no advert)
`/open` - Get list of unused hex keys
`/dupes` - Get list of duplicate repeater prefixes
`/prefix <hex>` - Check if a hex prefix is available
`/stats <hex>` - Get detailed stats of a repeater by hex prefix
`/reserve <prefix> <name>` - Reserve a hex prefix for a repeater
`/release <prefix>` - Release a hex prefix from the reserve list
`/help` - Show this help message

*All commands accept an optional `days` parameter (default: 7 days)*
*Data is refreshed every 30 minutes on the hour"""

            await ctx.respond(help_message)
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.respond("Error retrieving help information.")

if __name__ == "__main__":
    bot.run()