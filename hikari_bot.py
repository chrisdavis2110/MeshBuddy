#!/usr/bin/python

import hikari
import lightbulb
import configparser
import logging
import sys
import asyncio
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

# async def update_channel_name():
#     """Update Discord channel name with device counts"""
#     try:
#         # Get channel ID from config (you'll need to add this to config.ini)
#         channel_id = config.get("discord", "channel_id", fallback=None)
#         if not channel_id:
#             logger.warning("No channel_id specified in config.ini - skipping channel name update")
#             return

#         # Get device counts
#         data = bridge.load_data_from_json()
#         devices = extract_device_types(data, ['companions', 'repeaters', 'room_servers'], days=7)

#         if devices is None:
#             logger.warning("Could not get device data - skipping channel name update")
#             return

#         companion_count = len(devices.get('companions', []))
#         repeater_count = len(devices.get('repeaters', []))
#         room_server_count = len(devices.get('room_servers', []))

#         # Format channel name with emojis and counts
#         # Using Discord emojis: 🟢 (green circle), 🔵 (blue circle), 🟡 (yellow circle)
#         channel_name = f"🟢 {companion_count} 🔵 {repeater_count} 🟡 {room_server_count}"

#         # Update channel name
#         await bot.rest.edit_channel(int(channel_id), name=channel_name)
#         logger.info(f"Updated channel name to: {channel_name}")

#     except Exception as e:
#         logger.error(f"Error updating channel name: {e}")

# async def periodic_channel_update():
#     """Periodically update channel name"""
#     while True:
#         try:
#             await update_channel_name()
#             # Update every 5 minutes (300 seconds)
#             await asyncio.sleep(300)
#         except Exception as e:
#             logger.error(f"Error in periodic channel update: {e}")
#             # Wait 60 seconds before retrying on error
#             await asyncio.sleep(60)

# # Start periodic updates when bot starts
# @bot.listen()
# async def on_starting(event: hikari.StartingEvent):
#     """Start periodic channel updates when bot starts"""
#     asyncio.create_task(periodic_channel_update())

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
                # Format keys in chunks for Discord message limits
                keys_text = " ".join(unused_keys)
                if len(keys_text) > 2000:  # Discord message limit
                    message = f"Unused Keys ({len(unused_keys)} total):\n"
                    # Split into chunks
                    chunk_size = 50  # Approximate number of keys per chunk
                    for i in range(0, len(unused_keys), chunk_size):
                        chunk = unused_keys[i:i+chunk_size]
                        message += " ".join(f"{key:>2}" for key in chunk) + "\n"
                else:
                    message = f"Unused Keys ({len(unused_keys)} total):\n" + " ".join(f"{key:>2}" for key in unused_keys)
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

            # Get unused keys
            unused_keys = bridge.get_unused_keys(days=self.days)

            if unused_keys and hex_prefix in unused_keys:
                message = f"✅ {hex_prefix} is **AVAILABLE** for use!"
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
                    name = repeater.get('name', 'Unknown')
                    last_seen = repeater.get('last_seen', 'Unknown')
                    location = repeater.get('location', {'latitude': 0, 'longitude': 0})
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

                    message = f"Repeater {hex_prefix}:\n- Name: {name}\n- Last Seen: {formatted_last_seen}\n- Location: {lat}, {lon}"
                else:
                    # Multiple repeaters - show summary
                    message = f"Found {len(repeaters)} repeater(s) with prefix {hex_prefix}:\n\n"
                    for i, repeater in enumerate(repeaters, 1):
                        name = repeater.get('name', 'Unknown')
                        last_seen = repeater.get('last_seen', 'Unknown')
                        location = repeater.get('location', {'latitude': 0, 'longitude': 0})
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

                        message += f"**#{i}:** {name}\n\- Last Seen: {formatted_last_seen}\n\- Location: {lat}, {lon}\n\n"
            else:
                message = f"No repeater found with prefix {hex_prefix}."

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in stats command: {e}")
            await ctx.respond("Error retrieving repeater stats.")


# @client.register()
# class UpdateChannelCommand(lightbulb.SlashCommand, name="updatechannel",
#     description="Manually update the channel name with current device counts"):

#     @lightbulb.invoke
#     async def invoke(self, ctx: lightbulb.Context):
#         """Manually update channel name with device counts"""
#         try:
#             await ctx.respond("Updating channel name...")
#             await update_channel_name()
#             await ctx.respond("✅ Channel name updated successfully!")
#         except Exception as e:
#             logger.error(f"Error in updatechannel command: {e}")
#             await ctx.respond("❌ Error updating channel name.")

if __name__ == "__main__":
    bot.run()