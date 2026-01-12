"""
Bot Helpers Module

Contains helper functions for QR codes, role assignment, ownership management,
and repeater processing.
"""

import json
import os
import io
import urllib.parse
from datetime import datetime
import qrcode
import hikari
import lightbulb
from bot.core import bot, config, logger, CHECK, CROSS, WARN
from bot.utils import (
    get_owner_file_for_context,
    get_owner_file_for_category,
    get_removed_nodes_file_for_context,
    get_removed_nodes_file_for_category,
    is_node_removed,
    normalize_node
)


# ============================================================================
# QR Code Helpers
# ============================================================================

async def generate_and_send_qr(contact, ctx_or_interaction):
    """Generate QR code for a contact and send it"""
    try:
        name = contact.get('name', 'Unknown')
        public_key = contact.get('public_key', '')
        device_role = contact.get('device_role', 2)

        if not public_key:
            error_msg = f"{CROSS} Error: Contact has no public key"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_msg,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(error_msg, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # URL encode the parameters
        encoded_name = urllib.parse.quote(name)
        encoded_public_key = urllib.parse.quote(public_key)

        # Build the meshcore:// URL
        qr_url = f"meshcore://contact/add?name={encoded_name}&public_key={encoded_public_key}&type={device_role}"

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        img_data = img_bytes.getvalue()

        # Send as file attachment
        prefix = public_key[:2].upper() if public_key else '??'
        message = f"QR Code for {prefix}: {name}"

        # Create file attachment using hikari.Bytes
        filename = f"qr_{prefix}_{name.replace(' ', '_')}.png"
        file_obj = hikari.Bytes(img_data, filename)

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                attachments=[file_obj],
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(
                message,
                attachments=[file_obj],
                flags=hikari.MessageFlag.EPHEMERAL
            )
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        error_message = f"{CROSS} Error generating QR code: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)


# ============================================================================
# Role Assignment Helpers
# ============================================================================

async def assign_repeater_owner_role(user_id: int, guild_id: int | None, category_id: int | None = None):
    """Assign repeater owner roles to a user when they claim a repeater (both global and category-specific)"""
    try:
        if not user_id or not guild_id:
            return False

        # Collect all roles to assign
        roles_to_assign = []

        # Add global repeater role if configured
        global_role_id_str = config.get("discord", "repeater_owner_role_id", fallback=None)
        if global_role_id_str:
            try:
                global_role_id = int(global_role_id_str)
                roles_to_assign.append(global_role_id)
            except (ValueError, TypeError):
                pass

        # Add category-specific repeater role if configured
        if category_id:
            category_section = str(category_id)
            category_role_id_str = config.get(category_section, "repeater_owner_role_id", fallback=None)
            if category_role_id_str:
                try:
                    category_role_id = int(category_role_id_str)
                    if category_role_id not in roles_to_assign:
                        roles_to_assign.append(category_role_id)
                except (ValueError, TypeError):
                    pass

        if not roles_to_assign:
            logger.debug("No repeater_owner_role_id configured, skipping role assignment")
            return False

        # Check if user already has all roles
        try:
            member = await bot.rest.fetch_member(guild_id, user_id)
            missing_roles = [rid for rid in roles_to_assign if rid not in member.role_ids]
            if not missing_roles:
                logger.debug(f"User {user_id} already has all repeater roles")
                return True
        except Exception as e:
            logger.debug(f"Error checking existing roles: {e}")
            missing_roles = roles_to_assign  # Assign all if we can't check

        # Assign all missing roles
        assigned_count = 0
        for role_id in missing_roles:
            try:
                await bot.rest.add_role_to_member(guild_id, user_id, role_id)
                logger.info(f"Assigned role {role_id} to user {user_id} in guild {guild_id}")
                assigned_count += 1
            except hikari.ForbiddenError:
                logger.warning(f"Bot doesn't have permission to assign role {role_id} in guild {guild_id}")
            except Exception as e:
                logger.error(f"Error assigning role {role_id} to user {user_id}: {e}")

        return assigned_count > 0
    except hikari.NotFoundError as e:
        logger.warning(f"Role or user not found in guild {guild_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error assigning repeater owner roles: {e}")
        return False


# ============================================================================
# Ownership Helpers
# ============================================================================

async def get_owner_info_for_repeater(repeater, owner_file: str):
    """Get owner information for a repeater from the owner file"""
    try:
        public_key = repeater.get('public_key', '')
        if not public_key:
            return None

        if not os.path.exists(owner_file):
            return None

        with open(owner_file, 'r') as f:
            content = f.read().strip()
            if not content:
                return None
            owners_data = json.loads(content)

        # Find owner by public_key
        for owner in owners_data.get('data', []):
            if owner.get('public_key', '').upper() == public_key.upper():
                return owner

        return None
    except Exception as e:
        logger.debug(f"Error getting owner info: {e}")
        return None


async def get_user_display_name_from_member(ctx: lightbulb.Context, user_id: int | None, username: str) -> str:
    """Get the Discord server display name (nickname if set, otherwise username) for a user by fetching the member"""
    try:
        # If we have a user_id, try to fetch the member
        if user_id:
            try:
                # Get the guild from the channel
                channel = await bot.rest.fetch_channel(ctx.channel_id)
                if channel.guild_id:
                    member = await bot.rest.fetch_member(channel.guild_id, user_id)
                    # Return nickname if set, otherwise display_name, otherwise username
                    return member.nickname or member.display_name or username
            except Exception as e:
                logger.debug(f"Error fetching member for user_id {user_id}: {e}")
                # Fall back to username if member fetch fails

        # Fall back to username if we can't get display name
        return username
    except Exception as e:
        logger.debug(f"Error getting display name: {e}")
        return username


async def can_user_remove_repeater(repeater, user_id: int, ctx_or_interaction) -> tuple[bool, str]:
    """
    Check if a user can remove a repeater.

    Args:
        repeater: The repeater node to check
        user_id: The Discord user ID of the person trying to remove
        ctx_or_interaction: Context or interaction object for getting category info

    Returns:
        Tuple of (can_remove: bool, reason: str)
    """
    try:
        # Get bot owner ID from config
        bot_owner_id = None
        try:
            owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
            if owner_id_str:
                bot_owner_id = int(owner_id_str)
        except (ValueError, TypeError):
            pass

        # Check if user is the bot owner
        if bot_owner_id and user_id == bot_owner_id:
            return (True, "bot_owner")

        # Get owner file to check ownership
        if isinstance(ctx_or_interaction, lightbulb.Context):
            owner_file = await get_owner_file_for_context(ctx_or_interaction)
        elif hasattr(ctx_or_interaction, 'channel_id'):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                category_id = channel.parent_id
                owner_file = get_owner_file_for_category(category_id)
            except Exception:
                owner_file = "repeaterOwners.json"  # Fallback to default
        else:
            owner_file = "repeaterOwners.json"  # Fallback to default

        # Get owner info for this repeater
        owner_info = await get_owner_info_for_repeater(repeater, owner_file)

        if not owner_info:
            # No owner set, allow removal (unclaimed repeater)
            return (True, "no_owner")

        # Check if user is the owner
        owner_user_id = owner_info.get('user_id')
        if owner_user_id and int(owner_user_id) == user_id:
            return (True, "owner")

        # User is not the owner
        owner_display_name = owner_info.get('display_name') or owner_info.get('username', 'Unknown')
        return (False, f"Only the owner ({owner_display_name}) or bot owner can remove this repeater")

    except Exception as e:
        logger.error(f"Error checking if user can remove repeater: {e}")
        # On error, allow removal (fail open for safety)
        return (True, "error_check")


async def process_repeater_ownership(selected_repeater, ctx_or_interaction):
    """Process the ownership claim of a repeater and add to repeaterOwners.json (category-specific)"""
    try:
        # Get category-specific owner file
        if isinstance(ctx_or_interaction, lightbulb.Context):
            owner_file = await get_owner_file_for_context(ctx_or_interaction)
            username = ctx_or_interaction.user.username if ctx_or_interaction.user else "Unknown"
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            # For ComponentInteraction, we need to get category and user info
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                category_id = channel.parent_id
                owner_file = get_owner_file_for_category(category_id)
                username = ctx_or_interaction.user.username if ctx_or_interaction.user else "Unknown"
                user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
            except Exception:
                owner_file = "repeaterOwners.json"  # Fallback to default
                username = ctx_or_interaction.user.username if ctx_or_interaction.user else "Unknown"
                user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        else:
            owner_file = "repeaterOwners.json"  # Fallback to default
            username = "Unknown"
            user_id = None

        # Get display name (nickname if available)
        if isinstance(ctx_or_interaction, lightbulb.Context):
            display_name = await get_user_display_name_from_member(ctx_or_interaction, user_id, username)
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                if channel.guild_id and user_id:
                    member = await bot.rest.fetch_member(channel.guild_id, user_id)
                    display_name = member.nickname or member.display_name or username
                else:
                    display_name = username
            except Exception:
                display_name = username
        else:
            display_name = username

        public_key = selected_repeater.get('public_key', '')
        if not public_key:
            error_msg = f"{CROSS} Error: Repeater has no public key"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_msg,
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
            else:
                await ctx_or_interaction.respond(error_msg, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Load or create owner file
        if os.path.exists(owner_file):
            try:
                with open(owner_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        owners_data = json.loads(content)
                    else:
                        owners_data = {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }
            except json.JSONDecodeError:
                owners_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }
        else:
            owners_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        # Check if this public_key already exists
        existing_owner = None
        for owner in owners_data.get('data', []):
            if owner.get('public_key', '').upper() == public_key.upper():
                existing_owner = owner
                break

        prefix = public_key[:2].upper() if public_key else '??'
        name = selected_repeater.get('name', 'Unknown')

        if existing_owner:
            # Already claimed - show who owns it
            existing_username = existing_owner.get('username', 'Unknown')
            existing_display_name = existing_owner.get('display_name', None)
            if existing_display_name:
                message = f"{WARN} Repeater {prefix}: {name} is already claimed by **{existing_display_name}**"
            else:
                message = f"{WARN} Repeater {prefix}: {name} is already claimed by **{existing_username}**"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    message,
                    components=None,
                    flags=hikari.MessageFlag.EPHEMERAL
                )
            else:
                await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Add new owner entry
        owner_entry = {
            "public_key": public_key,
            "name": name,
            "username": username,  # Actual Discord username
            "display_name": display_name,  # Server nickname or display name
            "user_id": user_id
        }

        owners_data['data'].append(owner_entry)
        owners_data['timestamp'] = datetime.now().isoformat()

        # Save to file
        with open(owner_file, 'w') as f:
            json.dump(owners_data, f, indent=2)

        # Try to assign role to user
        guild_id = None
        category_id = None
        if isinstance(ctx_or_interaction, lightbulb.Context):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                guild_id = channel.guild_id
                category_id = channel.parent_id
            except Exception:
                pass
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                guild_id = channel.guild_id
                category_id = channel.parent_id
            except Exception:
                pass

        if user_id and guild_id:
            role_assigned = await assign_repeater_owner_role(user_id, guild_id, category_id)
            if role_assigned:
                message = f"{CHECK} Successfully claimed repeater {prefix}: **{name}**\n✅ Role assigned!"
            else:
                message = f"{CHECK} Successfully claimed repeater {prefix}: **{name}**"
        else:
            message = f"{CHECK} Successfully claimed repeater {prefix}: **{name}**"

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
        logger.error(f"Error processing repeater ownership: {e}")
        error_message = f"{CROSS} Error claiming repeater: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None,
                flags=hikari.MessageFlag.EPHEMERAL
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)


async def process_repeater_removal(selected_repeater, ctx_or_interaction):
    """Process the removal of a repeater to removedNodes.json (category-specific)"""
    try:
        # Get user ID from context/interaction
        if isinstance(ctx_or_interaction, lightbulb.Context):
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        elif isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            user_id = ctx_or_interaction.user.id if ctx_or_interaction.user else None
        else:
            user_id = None

        if not user_id:
            error_message = f"{CROSS} Unable to identify user"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_message,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Check if user can remove this repeater
        can_remove, reason = await can_user_remove_repeater(selected_repeater, user_id, ctx_or_interaction)
        if not can_remove:
            error_message = f"{CROSS} {reason}"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    error_message,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Get category-specific removed nodes file
        if isinstance(ctx_or_interaction, lightbulb.Context):
            removed_nodes_file = await get_removed_nodes_file_for_context(ctx_or_interaction)
        elif hasattr(ctx_or_interaction, 'channel_id'):
            # For ComponentInteraction, we need to create a temporary context-like object
            # or fetch the channel to get category
            try:
                channel = await bot.rest.fetch_channel(ctx_or_interaction.channel_id)
                category_id = channel.parent_id
                removed_nodes_file = get_removed_nodes_file_for_category(category_id)
            except Exception:
                removed_nodes_file = "removedNodes.json"  # Fallback to default
        else:
            removed_nodes_file = "removedNodes.json"  # Fallback to default
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
        selected_prefix = selected_repeater.get('public_key', '').upper() if selected_repeater.get('public_key') else ''
        selected_name = selected_repeater.get('name', '').strip()

        already_removed = False
        for removed_node in removed_data.get('data', []):
            removed_prefix = removed_node.get('public_key', '').upper() if removed_node.get('public_key') else ''
            removed_name = removed_node.get('name', '').strip()
            if removed_prefix == selected_prefix and removed_name == selected_name:
                already_removed = True
                break

        if already_removed:
            message = f"{WARN} Repeater {selected_prefix[:2]}: {selected_name} has already been removed"
            if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
                await ctx_or_interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    message,
                    components=None
                )
            else:
                await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
            return

        # Add node to removedNodes.json
        removed_data['data'].append(selected_repeater)
        removed_data['timestamp'] = datetime.now().isoformat()

        # Save removedNodes.json
        with open(removed_nodes_file, 'w') as f:
            json.dump(removed_data, f, indent=2)

        message = f"{CHECK} Repeater {selected_prefix[:2]}: {selected_name} has been removed"

        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                message,
                components=None
            )
        else:
            await ctx_or_interaction.respond(message, flags=hikari.MessageFlag.EPHEMERAL)
    except Exception as e:
        logger.error(f"Error processing repeater removal: {e}")
        error_message = f"{CROSS} Error removing repeater: {str(e)}"
        if isinstance(ctx_or_interaction, hikari.ComponentInteraction):
            await ctx_or_interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_UPDATE,
                error_message,
                components=None
            )
        else:
            await ctx_or_interaction.respond(error_message, flags=hikari.MessageFlag.EPHEMERAL)


async def check_reserved_repeater_and_add_owner(node, prefix, reserved_nodes_file="reservedNodes.json", owner_file="repeaterOwners.json"):
    """Check if a new repeater matches a reserved node and add to category-specific repeaterOwners file

    Returns:
        user_id (int | None): The user_id from the reservation if a match was found and owner was added, None otherwise
    """
    try:
        # Use the provided reserved_nodes_file (category-specific)
        if not os.path.exists(reserved_nodes_file):
            return None

        with open(reserved_nodes_file, 'r') as f:
            reserved_data = json.load(f)

        # Find matching reserved node by prefix
        matching_reservation = None
        for reserved_node in reserved_data.get('data', []):
            if reserved_node.get('prefix', '').upper() == prefix:
                matching_reservation = reserved_node
                break

        if not matching_reservation:
            return None

        # Get username, display_name, and user_id from reservation
        username = matching_reservation.get('username', 'Unknown')
        display_name = matching_reservation.get('display_name', username)  # Fallback to username if display_name not present
        user_id = matching_reservation.get('user_id', None)
        public_key = node.get('public_key', '')

        if not public_key:
            return None

        # Use the provided owner_file (category-specific)
        if os.path.exists(owner_file):
            try:
                with open(owner_file, 'r') as f:
                    owners_data = json.load(f)
            except (json.JSONDecodeError, Exception):
                owners_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }
        else:
            owners_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        # Check if this public_key already exists
        existing_owner = None
        for owner in owners_data.get('data', []):
            if owner.get('public_key', '').upper() == public_key.upper():
                existing_owner = owner
                break

        if existing_owner:
            # Already exists, skip
            return None

        # Add new owner entry
        owner_entry = {
            "public_key": public_key,
            "name": node.get('name', 'Unknown'),
            "username": username,
            "display_name": display_name,
            "user_id": user_id
        }

        owners_data['data'].append(owner_entry)
        owners_data['timestamp'] = datetime.now().isoformat()

        # Save to file
        with open(owner_file, 'w') as f:
            json.dump(owners_data, f, indent=2)

        logger.info(f"Added repeater owner: {username} (public_key: {public_key[:10]}...)")

        # Return user_id so caller can assign roles
        return user_id

    except Exception as e:
        logger.error(f"Error checking reserved repeater and adding owner: {e}")
        return None
