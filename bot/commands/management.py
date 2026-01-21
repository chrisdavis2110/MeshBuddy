"""
Management Commands

Commands for managing repeater reservations and ownership:
- reserve: Reserve a hex prefix for a repeater
- release: Release a hex prefix from the reserve list
- remove: Remove a repeater from the repeater list
- claim: Claim ownership of a repeater
- unclaim: Unclaim ownership of a repeater (owner or bot owner only)
- owner: Look up the owner of a repeater
"""

import json
import os
from datetime import datetime
import hikari
import lightbulb
from bot.core import client, config, logger, CHECK, CROSS, EMOJIS, category_check, pending_remove_selections, pending_own_selections, pending_unclaim_selections, pending_owner_selections
from bot.utils import (
    get_nodes_data_for_context,
    get_repeater_for_context,
    get_unused_keys_for_context,
    get_reserved_nodes_file_for_context,
    get_removed_nodes_file_for_context,
    get_owner_file_for_context,
    normalize_node,
    is_node_removed
)
from bot.helpers import (
    process_repeater_ownership,
    process_repeater_removal,
    process_repeater_unclaim,
    get_owner_info_for_repeater,
    get_user_display_name_from_member
)
from bot.events import display_owner_info


@client.register()
class ReserveRepeaterCommand(lightbulb.SlashCommand, name="reserve",
    description="Reserve a hex prefix for a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')
    name = lightbulb.string('name', 'Repeater name')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Reserve a hex prefix for a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            name = self.name.strip()

            # First, check if prefix is currently in use by an active repeater (within last 14 days)
            repeaters = await get_repeater_for_context(ctx, hex_prefix, days=14)
            if repeaters:
                # Filter out removed nodes
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]
                if repeaters:
                    repeater = repeaters[0]
                    current_name = repeater.get('name', 'Unknown')
                    await ctx.respond(
                        f"{CROSS} Prefix {hex_prefix} is **NOT AVAILABLE** - currently in use by: **{current_name}**\n"
                        f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                    )
                    return

            # Check if prefix is in unused keys (available for reservation) - uses 14 days
            unused_keys = await get_unused_keys_for_context(ctx, days=14)
            if unused_keys is None:
                await ctx.respond("Error: Could not check prefix availability. Please try again.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # If prefix is not in unused keys, it's not available
            if hex_prefix not in unused_keys:
                await ctx.respond(
                    f"{CROSS} Prefix {hex_prefix} is **NOT AVAILABLE** for reservation.\n"
                    f"*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*",
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                return

            # Load existing reservedNodes.json or create new structure
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if os.path.exists(reserved_nodes_file):
                with open(reserved_nodes_file, 'r') as f:
                    reserved_data = json.load(f)
            else:
                reserved_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }

            # Check if prefix already exists in reserved list
            existing_node = None
            for node in reserved_data['data']:
                if node.get('prefix', '').upper() == hex_prefix:
                    existing_node = node
                    break

            if existing_node:
                existing_name = existing_node.get('name', 'Unknown')
                existing_display_name = existing_node.get('display_name', existing_node.get('username', 'Unknown'))
                await ctx.respond(
                    f"{CROSS} {hex_prefix} with name: **{existing_name}** has already been reserved by **{existing_display_name}**\n*You can only reserve prefixes from the unused keys list. Use `/open` to see available prefixes.*"
                )
                return
            # Get username and user_id from context
            username = ctx.user.username if ctx.user else "Unknown"
            user_id = ctx.user.id if ctx.user else None

            # Fetch and save the user's display name (server nickname if available)
            display_name = await get_user_display_name_from_member(ctx, user_id, username)

            # Create node entry - save both username and display_name, and also save user_id
            node_entry = {
                "prefix": hex_prefix,
                "name": name,
                "username": username,  # Actual Discord username
                "display_name": display_name,  # Display name (nickname if available, otherwise username)
                "user_id": user_id,
                "added_at": datetime.now().isoformat()
            }

            # Add new entry
            reserved_data['data'].append(node_entry)
            message = f"{CHECK} Reserved hex prefix {hex_prefix} for repeater: **{name}**"

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in reserve command: {e}")
            await ctx.respond(f"Error reserving hex prefix for repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class ReleaseRepeaterCommand(lightbulb.SlashCommand, name="release",
    description="Release a hex prefix for a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Release a hex prefix for a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get bot owner ID from config
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            # Get current user ID
            user_id = ctx.user.id if ctx.user else None
            if not user_id:
                await ctx.respond("Error: Could not identify user.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load existing reservedNodes.json
            reserved_nodes_file = await get_reserved_nodes_file_for_context(ctx)
            if not os.path.exists(reserved_nodes_file):
                await ctx.respond("Error: list does not exist)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            with open(reserved_nodes_file, 'r') as f:
                reserved_data = json.load(f)

            # Find the reserved node entry
            reserved_node = None
            for node in reserved_data.get('data', []):
                if node.get('prefix', '').upper() == hex_prefix:
                    reserved_node = node
                    break

            if not reserved_node:
                await ctx.respond(f"{CROSS} {hex_prefix} is not reserved for a repeater",
                    flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Check if user is the bot owner
            is_bot_owner = bot_owner_id and user_id == bot_owner_id

            # Check if user is the one who reserved it
            reserved_user_id = reserved_node.get('user_id')
            is_reserver = reserved_user_id and int(reserved_user_id) == user_id

            # Only allow release if user is bot owner or the person who reserved it
            if not is_bot_owner and not is_reserver:
                reserved_display_name = reserved_node.get('display_name', reserved_node.get('username', 'Unknown'))
                await ctx.respond(
                    f"{CROSS} Only the person who reserved {hex_prefix} ({reserved_display_name}) or the bot owner can release it.",
                    flags=hikari.MessageFlag.EPHEMERAL
                )
                return

            # Find the entry to remove
            reserved_data['data'] = [
                node for node in reserved_data['data']
                if node.get('prefix', '').upper() != hex_prefix
            ]

            # Update timestamp
            reserved_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(reserved_nodes_file, 'w') as f:
                json.dump(reserved_data, f, indent=2)

            message = f"{CHECK} Released hex prefix {hex_prefix}"
            await ctx.respond(message)
        except Exception as e:
            logger.error(f"Error in release command: {e}")
            await ctx.respond(f"Error releasing hex prefix: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class RemoveNodeCommand(lightbulb.SlashCommand, name="remove",
    description="Remove a repeater from the repeater list", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Remove a node from nodes.json and copy it to removedNodes.json"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    # Check if already removed using removed nodes file
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}")
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
            await ctx.respond(f"Error removing repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class ClaimRepeaterCommand(lightbulb.SlashCommand, name="claim",
    description="Claim ownership of a repeater", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Claim ownership of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}", flags=hikari.MessageFlag.EPHEMERAL)
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
                custom_id = f"own_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters for later retrieval
                pending_own_selections[custom_id] = matching_repeaters

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to claim",
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

                await ctx.respond(
                    f"Found {len(matching_repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, use it directly
                selected_repeater = matching_repeaters[0]

            # Process the ownership claim (for single repeater case)
            await process_repeater_ownership(selected_repeater, ctx)
        except Exception as e:
            logger.error(f"Error in claim command: {e}")
            await ctx.respond(f"Error claiming repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class UnclaimRepeaterCommand(lightbulb.SlashCommand, name="unclaim",
    description="Unclaim ownership of a repeater (owner or bot owner only)", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Unclaim ownership of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}", flags=hikari.MessageFlag.EPHEMERAL)
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
                custom_id = f"unclaim_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters for later retrieval
                pending_unclaim_selections[custom_id] = matching_repeaters

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to unclaim",
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

                await ctx.respond(
                    f"Found {len(matching_repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, use it directly
                selected_repeater = matching_repeaters[0]

            # Process the ownership unclaim (for single repeater case)
            await process_repeater_unclaim(selected_repeater, ctx)
        except Exception as e:
            logger.error(f"Error in unclaim command: {e}")
            await ctx.respond(f"Error unclaiming repeater: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class OwnerRepeaterCommand(lightbulb.SlashCommand, name="owner",
    description="Look up the owner of a repeater", hooks=[category_check], default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Look up the owner of a repeater"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) != 2 or not all(c in '0123456789ABCDEF' for c in hex_prefix):
                await ctx.respond("Invalid hex format. Please use 2 characters (00-FF), e.g., `A1`", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Load nodes.json
            nodes_data = await get_nodes_data_for_context(ctx)
            if nodes_data is None:
                await ctx.respond("Error: nodes data not found", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Find all repeaters with matching prefix (device_role == 2)
            nodes_list = nodes_data.get('data', [])
            matching_repeaters = []

            for node in nodes_list:
                # Normalize field names
                normalize_node(node)
                node_prefix = node.get('public_key', '')[:2].upper() if node.get('public_key') else ''
                # Only consider repeaters (device_role == 2)
                if node_prefix == hex_prefix and node.get('device_role') == 2:
                    # Check if already removed
                    removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                    if not is_node_removed(node, removed_nodes_file):
                        matching_repeaters.append(node)

            if not matching_repeaters:
                await ctx.respond(f"{CROSS} No repeater found with hex prefix {hex_prefix}", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get owner file
            owner_file = await get_owner_file_for_context(ctx)

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

                    # Check if this repeater has an owner
                    owner_info = await get_owner_info_for_repeater(repeater, owner_file)
                    owner_status = " (claimed)" if owner_info else " (unclaimed)"

                    # Create option label (Discord limit: 100 chars)
                    label = f"{name[:45]}{owner_status}"[:100]  # Truncate name if too long
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
                custom_id = f"owner_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters and owner file for later retrieval
                pending_owner_selections[custom_id] = (matching_repeaters, owner_file)

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to view owner",
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

                await ctx.respond(
                    f"Found {len(matching_repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, display owner info directly
                selected_repeater = matching_repeaters[0]
                await display_owner_info(selected_repeater, owner_file, ctx)
        except Exception as e:
            logger.error(f"Error in owner command: {e}")
            await ctx.respond(f"{CROSS} Error looking up owner: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
