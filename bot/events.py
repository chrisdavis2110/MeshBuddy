"""
Bot Events Module

Contains event handlers for Discord events:
- Bot startup
- Component interactions
- Reaction add/remove events
"""

import json
import os
import asyncio
import threading
import hikari
from bot.core import bot, config, logger, CROSS, pending_remove_selections, pending_qr_selections, pending_own_selections, pending_unclaim_selections, pending_owner_selections
from bot.utils import get_owner_file_for_category, get_server_emoji
from bot.helpers import (
    generate_and_send_qr,
    process_repeater_ownership,
    process_repeater_removal,
    process_repeater_unclaim,
    get_owner_info_for_repeater
)
from bot.tasks import (
    periodic_channel_update,
    periodic_node_watcher,
    periodic_message_purge
)


# ============================================================================
# Bot Startup Event
# ============================================================================

@bot.listen()
async def on_starting(event: hikari.StartingEvent):
    """Start periodic channel updates, node watcher, and MQTT subscriber when bot starts"""
    from bot.utils import initialize_emojis

    # Initialize emojis after a short delay to ensure bot is ready
    async def init_emojis_delayed():
        await asyncio.sleep(5)  # Wait for bot to be fully ready
        await initialize_emojis()

    asyncio.create_task(init_emojis_delayed())
    asyncio.create_task(periodic_channel_update())
    asyncio.create_task(periodic_node_watcher())
    asyncio.create_task(periodic_message_purge())

    # Start MQTT subscriber or API polling based on config
    def start_mqtt_subscriber():
        """Start MQTT subscriber in a separate thread"""
        try:
            from mqtt.subscriber import MQTTSubscriber
            subscriber = MQTTSubscriber()
            subscriber.start()
        except Exception as e:
            logger.error(f"Error starting MQTT subscriber: {e}")

    def start_api_polling():
        """Start API polling in a separate thread"""
        try:
            from mqtt.subscriber import MQTTSubscriber
            subscriber = MQTTSubscriber()
            # Force API mode by disabling MQTT
            subscriber.use_mqtt = False
            subscriber.start_api_polling()
        except Exception as e:
            logger.error(f"Error starting API polling: {e}")

    # Check which service is enabled
    try:
        mqtt_enabled = config.getboolean("mqtt", "mqtt_enabled", fallback=False)
        api_enabled = config.getboolean("api", "api_enabled", fallback=False)

        if mqtt_enabled:
            # MQTT is enabled, start MQTT subscriber
            mqtt_thread = threading.Thread(target=start_mqtt_subscriber, daemon=True, name="MQTTSubscriber")
            mqtt_thread.start()
            logger.info("MQTT subscriber started in background thread")
        elif api_enabled:
            # API is enabled but MQTT is not, start API polling
            api_thread = threading.Thread(target=start_api_polling, daemon=True, name="APIPolling")
            api_thread.start()
            logger.info("API polling started in background thread")
        else:
            logger.info("Both MQTT and API are disabled in config - no data source will be used")
    except Exception as e:
        logger.warning(f"Could not start data source: {e}")


# ============================================================================
# Component Interaction Event
# ============================================================================

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
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )

    # Check if this is a QR code selection
    elif custom_id and custom_id.startswith("qr_select_"):
        # Extract the custom_id to get the matching repeaters
        if custom_id in pending_qr_selections:
            matching_repeaters = pending_qr_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Generate and send QR code
                await generate_and_send_qr(selected_repeater, interaction)

                # Clean up the stored selection
                del pending_qr_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )

    # Check if this is an own/claim selection
    elif custom_id and custom_id.startswith("own_select_"):
        # Extract the custom_id to get the matching repeaters
        if custom_id in pending_own_selections:
            matching_repeaters = pending_own_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Process the ownership claim
                await process_repeater_ownership(selected_repeater, interaction)

                # Clean up the stored selection
                del pending_own_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                del pending_own_selections[custom_id]

    # Check if this is an unclaim selection
    elif custom_id and custom_id.startswith("unclaim_select_"):
        # Extract the custom_id to get the matching repeaters
        if custom_id in pending_unclaim_selections:
            matching_repeaters = pending_unclaim_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Process the ownership unclaim
                await process_repeater_unclaim(selected_repeater, interaction)

                # Clean up the stored selection
                del pending_unclaim_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                del pending_unclaim_selections[custom_id]

    # Check if this is an owner lookup selection
    elif custom_id and custom_id.startswith("owner_select_"):
        # Extract the custom_id to get the matching repeaters and owner file
        if custom_id in pending_owner_selections:
            matching_repeaters, owner_file = pending_owner_selections[custom_id]

            # Get the selected index
            if interaction.values and len(interaction.values) > 0:
                selected_index = int(interaction.values[0])
                selected_repeater = matching_repeaters[selected_index]

                # Display owner info
                await display_owner_info(selected_repeater, owner_file, interaction)

                # Clean up the stored selection
                del pending_owner_selections[custom_id]
            else:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )


# ============================================================================
# Reaction Events
# ============================================================================

@bot.listen()
async def on_reaction_add(event: hikari.GuildReactionAddEvent):
    """Handle reaction add events for role assignment"""
    try:
        # Ignore bot reactions
        if event.member and event.member.is_bot:
            return

        # Load reaction roles mappings
        roles_file = "reaction_roles.json"
        if not os.path.exists(roles_file):
            return

        with open(roles_file, 'r') as f:
            roles_data = json.load(f)

        # Find mapping for this message and emoji
        message_id = str(event.message_id)
        emoji_str = None

        # Handle emoji - could be UnicodeEmoji object or custom emoji
        if event.emoji_id:
            # Custom emoji
            emoji_name = str(event.emoji_name) if event.emoji_name else ""
            emoji_str = f"<:{emoji_name}:{event.emoji_id}>"
        elif event.emoji_name:
            # Unicode emoji - could be UnicodeEmoji object or string
            emoji_str = str(event.emoji_name)

        if not emoji_str:
            return

        mapping = None
        for m in roles_data.get("mappings", []):
            if m.get("message_id") == message_id:
                # Compare emoji
                mapping_emoji = m.get("emoji", "")
                if mapping_emoji == emoji_str or mapping_emoji == event.emoji_name:
                    mapping = m
                    break

        if not mapping:
            return

        # Assign the role
        role_id = int(mapping["role_id"])
        guild_id = event.guild_id

        if not guild_id or not event.user_id:
            return

        try:
            await bot.rest.add_role_to_member(guild_id, event.user_id, role_id)
            logger.info(f"Assigned role {role_id} to user {event.user_id} via reaction")
        except hikari.ForbiddenError:
            logger.warning(f"Bot doesn't have permission to assign role {role_id}")
        except Exception as e:
            logger.error(f"Error assigning role via reaction: {e}")
    except Exception as e:
        logger.error(f"Error in reaction add handler: {e}")


@bot.listen()
async def on_reaction_remove(event: hikari.GuildReactionDeleteEvent):
    """Handle reaction remove events for role removal"""
    try:
        # Load reaction roles mappings
        roles_file = "reaction_roles.json"
        if not os.path.exists(roles_file):
            return

        with open(roles_file, 'r') as f:
            roles_data = json.load(f)

        # Find mapping for this message and emoji
        message_id = str(event.message_id)
        emoji_str = None

        # Handle emoji - could be UnicodeEmoji object or string
        if event.emoji_id:
            # Custom emoji
            emoji_name = str(event.emoji_name) if event.emoji_name else ""
            emoji_str = f"<:{emoji_name}:{event.emoji_id}>"
        elif event.emoji_name:
            # Unicode emoji - could be UnicodeEmoji object or string
            emoji_str = str(event.emoji_name)

        if not emoji_str:
            return

        mapping = None
        for m in roles_data.get("mappings", []):
            if m.get("message_id") == message_id:
                # Compare emoji
                mapping_emoji = m.get("emoji", "")
                if mapping_emoji == emoji_str or mapping_emoji == str(event.emoji_name):
                    mapping = m
                    break

        if not mapping:
            return

        # GuildReactionDeleteEvent doesn't have user_id, so we need to fetch the message
        # and check who still has the reaction, then remove role from those who don't
        guild_id = event.guild_id
        channel_id = event.channel_id
        role_id = int(mapping["role_id"])

        if not guild_id or not channel_id:
            return

        try:
            # Fetch the message to get current reactions
            message = await bot.rest.fetch_message(channel_id, event.message_id)

            # Find the reaction for this emoji
            reaction = None
            reaction_emoji = None
            for r in message.reactions or []:
                # Compare reactions
                if event.emoji_id:
                    # Custom emoji
                    if r.emoji and r.emoji.id == event.emoji_id:
                        reaction = r
                        reaction_emoji = r.emoji
                        break
                elif event.emoji_name:
                    # Unicode emoji
                    if r.emoji and str(r.emoji) == str(event.emoji_name):
                        reaction = r
                        reaction_emoji = r.emoji
                        break

            # Get users who currently have the reaction
            users_with_reaction = set()
            if reaction and reaction_emoji:
                try:
                    async for user in bot.rest.fetch_reactions_for_emoji(channel_id, message_id, reaction_emoji):
                        users_with_reaction.add(user.id)
                except Exception as e:
                    logger.debug(f"Error fetching reaction users: {e}")

            # Get all members with the role
            try:
                guild = await bot.rest.fetch_guild(guild_id)
                async for member in bot.rest.fetch_members(guild_id):
                    # Check if member has the role but doesn't have the reaction
                    if role_id in member.role_ids and member.id not in users_with_reaction:
                        # Member has role but no longer has reaction - remove role
                        try:
                            await bot.rest.remove_role_from_member(guild_id, member.id, role_id)
                            logger.info(f"Removed role {role_id} from user {member.id} via reaction removal")
                        except Exception as e:
                            logger.debug(f"Error removing role from {member.id}: {e}")
            except Exception as e:
                logger.error(f"Error fetching guild members: {e}")

        except Exception as e:
            logger.error(f"Error handling reaction removal: {e}")
    except Exception as e:
        logger.error(f"Error in reaction remove handler: {e}")


# ============================================================================
# Helper Functions for Events
# ============================================================================

async def display_owner_info(repeater, owner_file: str, ctx_or_interaction):
    """Display owner information for a repeater"""
    try:
        from bot.core import WARN

        public_key = repeater.get('public_key', '')
        name = repeater.get('name', 'Unknown')
        prefix = public_key[:2].upper() if public_key else '??'

        # Get owner info
        owner_info = await get_owner_info_for_repeater(repeater, owner_file)

        if owner_info:
            owner_username = owner_info.get('username', 'Unknown')
            owner_display_name = owner_info.get('display_name', None)
            owner_user_id = owner_info.get('user_id', None)

            message = f"Repeater **{prefix}: {name}**\n"
            if owner_display_name:
                message += f"Owner: **{owner_display_name}**"
            else:
                message += f"Owner: **{owner_username}**"
            # if owner_user_id:
            #     message += f" (<@{owner_user_id}>)"
        else:
            message = f"**Repeater {prefix}: {name}**\n"
            message += f"{WARN} No owner claimed for this repeater"

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
    except Exception as e:
        logger.error(f"Error displaying owner info: {e}")
        error_message = f"Error displaying owner information: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)
