"""
Bot Events Module

Contains event handlers for Discord events:
- on_starting: Initializes periodic tasks and MQTT subscriber on bot startup.
- on_component_interaction: Handles interactions with select menus for remove, QR code, ownership claim, unclaim, and owner lookup.
- on_reaction_add: Handles adding roles based on reactions.
- on_reaction_remove: Handles removing roles based on reaction removals.
- display_owner_info: Display owner information for a repeater.
"""

import json
import os
import asyncio
import threading
from datetime import datetime
import hikari
from bot.core import bot, config, logger, CROSS, pending_remove_selections, pending_qr_selections, pending_own_selections, pending_unclaim_selections, pending_owner_selections, pending_release_selections
from bot.utils import get_owner_file_for_channel, get_server_emoji, get_prefix_length_for_channel_id
from bot.helpers import (
    generate_and_send_qr,
    process_repeater_ownership,
    process_repeater_removal,
    process_repeater_unclaim,
    get_owner_info_for_repeater
)
from bot.tasks import (
    periodic_channel_update,
    periodic_node_watcher
)


# ============================================================================
# Bot Startup Event
# ============================================================================

def initialize_json_files():
    """Initialize required JSON files if they don't exist"""
    files_to_init = [
        "nodes.json",
        "reservedNodes.json",
        "repeaterOwners.json",
        "offReserved.json"
    ]

    for filename in files_to_init:
        if not os.path.exists(filename):
            try:
                # Create empty structure with timestamp and empty data array
                empty_data = {
                    "timestamp": datetime.now().isoformat() + 'Z',
                    "data": []
                }

                with open(filename, 'w') as f:
                    json.dump(empty_data, f, indent=2)

                logger.info(f"Initialized {filename}")
            except Exception as e:
                logger.error(f"Error initializing {filename}: {e}")


@bot.listen()
async def on_starting(event: hikari.StartingEvent):
    """Start periodic channel updates, node watcher, and MQTT subscriber when bot starts"""
    from bot.utils import initialize_emojis

    # Initialize JSON files if they don't exist
    initialize_json_files()

    # Initialize emojis after a short delay to ensure bot is ready
    async def init_emojis_delayed():
        await asyncio.sleep(5)  # Wait for bot to be fully ready
        await initialize_emojis()

    asyncio.create_task(init_emojis_delayed())
    asyncio.create_task(periodic_channel_update())
    asyncio.create_task(periodic_node_watcher())

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

    # Check if this is a release selection
    elif custom_id and custom_id.startswith("release_select_"):
        if custom_id in pending_release_selections:
            payload = pending_release_selections[custom_id]
            matches, reserved_nodes_file, bot_owner_id = payload
            if not interaction.values or len(interaction.values) == 0:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    f"{CROSS} No selection made",
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                del pending_release_selections[custom_id]
            else:
                selected_index = int(interaction.values[0])
                selected_node = matches[selected_index]
                hex_prefix = (selected_node.get("prefix") or "").upper()
                user_id = interaction.user.id if interaction.user else None
                if not user_id:
                    await interaction.create_initial_response(
                        hikari.ResponseType.MESSAGE_UPDATE,
                        f"{CROSS} Unable to identify user",
                        components=None,
                        flags=hikari.MessageFlag.EPHEMERAL
                    )
                    del pending_release_selections[custom_id]
                else:
                    is_bot_owner = bot_owner_id and user_id == bot_owner_id
                    reserved_user_id = selected_node.get("user_id")
                    is_reserver = reserved_user_id and int(reserved_user_id) == user_id
                    if not is_bot_owner and not is_reserver:
                        display_name = selected_node.get("display_name") or selected_node.get("username") or "Unknown"
                        await interaction.create_initial_response(
                            hikari.ResponseType.MESSAGE_UPDATE,
                            f"{CROSS} Only the person who reserved {hex_prefix} ({display_name}) or the bot owner can release it.",
                            components=None,
                            flags=hikari.MessageFlag.EPHEMERAL
                        )
                        del pending_release_selections[custom_id]
                    else:
                        try:
                            with open(reserved_nodes_file, "r") as f:
                                reserved_data = json.load(f)
                            reserved_data["data"] = [
                                n for n in reserved_data.get("data", [])
                                if (n.get("prefix") or "").upper() != hex_prefix
                            ]
                            reserved_data["timestamp"] = datetime.now().isoformat()
                            with open(reserved_nodes_file, "w") as f:
                                json.dump(reserved_data, f, indent=2)
                            channel = await bot.rest.fetch_channel(interaction.channel_id)
                            category_id = getattr(channel, "parent_id", None)
                            if category_id:
                                command_history.mark_reservation_released(category_id)
                            await interaction.create_initial_response(
                                hikari.ResponseType.MESSAGE_UPDATE,
                                f"{CHECK} Released hex prefix {hex_prefix}",
                                components=None
                            )
                        except Exception as e:
                            logger.error(f"Error processing release selection: {e}")
                            await interaction.create_initial_response(
                                hikari.ResponseType.MESSAGE_UPDATE,
                                f"{CROSS} Error releasing: {str(e)}",
                                components=None,
                                flags=hikari.MessageFlag.EPHEMERAL
                            )
                        del pending_release_selections[custom_id]

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
# Helper Functions for Events
# ============================================================================

async def display_owner_info(repeater, owner_file: str, ctx_or_interaction):
    """Display owner information for a repeater"""
    try:
        from bot.core import WARN

        public_key = repeater.get('public_key', '')
        name = repeater.get('name', 'Unknown')
        prefix_length = await get_prefix_length_for_channel_id(ctx_or_interaction.channel_id)
        prefix = public_key[:prefix_length].upper() if public_key else '????'

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
