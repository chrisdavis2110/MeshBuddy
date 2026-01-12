"""
Admin Commands

Administrative commands for bot management:
- purge: Delete old messages from a channel
- setup_roles: Set up a reaction roles message
- add_role_reaction: Add an emoji-role mapping to a roles message
- remove_role_reaction: Remove an emoji-role mapping from a roles message
"""

import json
import os
import hikari
import lightbulb
from bot.core import client, bot, config, logger, CHECK, CROSS, WARN
from bot.tasks import purge_old_messages_from_channel


@client.register()
class PurgeOldMessagesCommand(lightbulb.SlashCommand, name="purge",
    description="Delete old messages from a channel (uses configured purge_days)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    channel = lightbulb.channel('channel', 'Channel to purge messages from (defaults to current channel)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Delete old messages from a channel (uses purge_days from config, default: 4 days)"""
        try:
            # Determine which channel to purge
            target_channel_id = self.channel.id if self.channel else ctx.channel_id
            target_channel = await bot.rest.fetch_channel(target_channel_id)

            # Check if channel is a text channel, news channel, or forum channel
            if not isinstance(target_channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel, hikari.GuildForumChannel)):
                await ctx.respond(f"{CROSS} This command can only be used in text, news, or forum channels.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Check permissions - need MANAGE_MESSAGES permission
            if not ctx.member:
                await ctx.respond(f"{CROSS} Unable to verify permissions.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get guild to check permissions
            if not target_channel.guild_id:
                await ctx.respond(f"{CROSS} This command can only be used in guild channels.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Check if user has MANAGE_MESSAGES permission
            permissions = ctx.member.get_permissions()
            if not (permissions & hikari.Permissions.MANAGE_MESSAGES):
                await ctx.respond(f"{CROSS} You need the MANAGE_MESSAGES permission to use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Get purge days from config for the message
            try:
                purge_days = int(config.get("discord", "purge_days", fallback="4"))
            except (ValueError, TypeError):
                purge_days = 4

            # Send initial response
            await ctx.respond(f"{WARN} Starting to purge messages older than {purge_days} days from <#{target_channel_id}>... This may take a while.", flags=hikari.MessageFlag.EPHEMERAL)

            # Use the shared purge function
            deleted_count, failed_count = await purge_old_messages_from_channel(target_channel_id)

            # Send completion message
            result_message = f"{CHECK} Purge complete! Deleted {deleted_count} message(s)"
            if failed_count > 0:
                result_message += f", {failed_count} message(s) could not be deleted"
            result_message += "."

            try:
                await ctx.interaction.edit_initial_response(result_message)
            except Exception as e:
                logger.error(f"Error editing initial response: {e}")
                # Try to send a follow-up message instead
                await ctx.respond(result_message, flags=hikari.MessageFlag.EPHEMERAL)

        except Exception as e:
            logger.error(f"Error in purge command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await ctx.interaction.edit_initial_response(f"{CROSS} Error purging messages: {str(e)}")
            except Exception:
                await ctx.respond(f"{CROSS} Error purging messages: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class SetupRolesCommand(lightbulb.SlashCommand, name="setup_roles",
    description="Set up a reaction roles message (admin only)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    channel = lightbulb.channel('channel', 'Channel to post the roles message in')
    message = lightbulb.string('message', 'Message content for the roles message')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Set up a reaction roles message"""
        try:
            # Check if user is bot owner
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
                await ctx.respond(f"{CROSS} Only the bot owner can use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Determine channel - check config first, then parameter, then current channel
            target_channel_id = None

            # Check config for role_channel_id
            role_channel_id_str = config.get("discord", "role_channel_id", fallback=None)
            if role_channel_id_str:
                try:
                    target_channel_id = int(role_channel_id_str)
                except (ValueError, TypeError):
                    pass

            # Override with parameter if provided
            if self.channel:
                target_channel_id = self.channel.id

            # Fall back to current channel if nothing else
            if not target_channel_id:
                target_channel_id = ctx.channel_id

            target_channel = await bot.rest.fetch_channel(target_channel_id)

            if not isinstance(target_channel, hikari.GuildTextChannel):
                await ctx.respond(f"{CROSS} This command can only be used in text channels.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Default message if not provided
            roles_message = self.message if self.message else "**React to get roles:**\n\nReact with the emoji below to get the corresponding role!"

            # Send the message
            sent_message = await bot.rest.create_message(target_channel_id, roles_message)

            # Store the message ID in config or a file for tracking
            # For now, we'll use a simple approach - store in a JSON file
            roles_file = "reaction_roles.json"
            if os.path.exists(roles_file):
                try:
                    with open(roles_file, 'r') as f:
                        roles_data = json.load(f)
                except:
                    roles_data = {"messages": []}
            else:
                roles_data = {"messages": []}

            # Add this message to the list
            roles_data["messages"].append({
                "message_id": str(sent_message.id),
                "channel_id": str(target_channel_id),
                "guild_id": str(target_channel.guild_id) if target_channel.guild_id else None
            })

            with open(roles_file, 'w') as f:
                json.dump(roles_data, f, indent=2)

            await ctx.respond(
                f"{CHECK} Roles message created in <#{target_channel_id}>!\n"
                f"Message ID: {sent_message.id}\n\n"
                f"**Next steps:**\n"
                f"1. Use `/add_role_reaction` to add emoji-role mappings to this message\n"
                f"2. Users can then react to get roles automatically",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error in setup_roles command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.respond(f"{CROSS} Error setting up roles message: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class AddRoleReactionCommand(lightbulb.SlashCommand, name="add_role_reaction",
    description="Add an emoji-role mapping to a roles message (admin only)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    message_id = lightbulb.string('message_id', 'The message ID to add reactions to')
    emoji = lightbulb.string('emoji', 'The emoji to use (e.g., ✅ or :checkmark:)')
    role = lightbulb.role('role', 'The role to assign when this emoji is reacted')
    description = lightbulb.string('description', 'Description of what this role is for')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Add an emoji-role mapping to a roles message"""
        try:
            # Check if user is bot owner
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
                await ctx.respond(f"{CROSS} Only the bot owner can use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            message_id = int(self.message_id)
            role_id = self.role.id
            emoji_str = self.emoji.strip()
            description = self.description.strip()

            # Try to find the message
            roles_file = "reaction_roles.json"
            if not os.path.exists(roles_file):
                await ctx.respond(f"{CROSS} No roles messages found. Use `/setup_roles` first.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            with open(roles_file, 'r') as f:
                roles_data = json.load(f)

            # Find the message
            message_info = None
            for msg in roles_data.get("messages", []):
                if str(msg.get("message_id")) == str(message_id):
                    message_info = msg
                    break

            if not message_info:
                await ctx.respond(f"{CROSS} Message ID not found in roles messages.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            channel_id = int(message_info["channel_id"])

            # Add reaction to the message
            try:
                # Hikari's REST API accepts emoji as:
                # - Unicode emoji string (e.g., "✅")
                # - Custom emoji in format "name:id" (NOT "<:name:id>")
                # - Or fetch the emoji object from the guild

                emoji_obj = None
                is_animated = False

                # Try to parse as custom emoji first (Discord format: <:name:id> or <a:name:id>)
                if emoji_str.startswith('<') and emoji_str.endswith('>'):
                    # Custom emoji format: <:name:id> or <a:name:id>
                    parts = emoji_str[1:-1].split(':')
                    if len(parts) == 3:
                        is_animated = parts[0] == 'a'
                        emoji_name = parts[1]
                        emoji_id = parts[2]
                        # Hikari expects "name:id" format (without angle brackets)
                        emoji_obj = f"{emoji_name}:{emoji_id}"
                    else:
                        await ctx.respond(f"{CROSS} Invalid emoji format. Use a standard emoji (✅) or custom emoji format (<:name:id> or <a:name:id>).", flags=hikari.MessageFlag.EPHEMERAL)
                        return
                elif emoji_str.startswith(':') and emoji_str.endswith(':'):
                    # Emoji name format: :emoji_name: - try to find it in the guild
                    emoji_name = emoji_str[1:-1]  # Remove colons
                    try:
                        # Try to find the emoji in the guild
                        channel = await bot.rest.fetch_channel(channel_id)
                        if channel.guild_id:
                            guild = await bot.rest.fetch_guild(channel.guild_id)
                            # Search for emoji by name
                            for emoji in guild.get_emojis() or []:
                                if emoji.name == emoji_name:
                                    # Found guild emoji - use "name:id" format
                                    emoji_obj = f"{emoji.name}:{emoji.id}"
                                    is_animated = emoji.is_animated
                                    break

                        if not emoji_obj:
                            await ctx.respond(f"{CROSS} Emoji ':{emoji_name}:' not found in this guild.", flags=hikari.MessageFlag.EPHEMERAL)
                            return
                    except Exception as e:
                        logger.error(f"Error searching for guild emoji: {e}")
                        await ctx.respond(f"{CROSS} Error searching for emoji: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
                        return
                else:
                    # Unicode emoji - use as-is
                    emoji_obj = emoji_str

                if not emoji_obj:
                    await ctx.respond(f"{CROSS} Could not determine emoji format.", flags=hikari.MessageFlag.EPHEMERAL)
                    return

                await bot.rest.add_reaction(channel_id, message_id, emoji_obj)
            except Exception as e:
                logger.error(f"Error adding reaction: {e}")
                await ctx.respond(f"{CROSS} Error adding reaction to message: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Store the mapping
            if "mappings" not in roles_data:
                roles_data["mappings"] = []

            # Check if mapping already exists
            mapping_key = f"{message_id}:{emoji_str}"
            existing = False
            for mapping in roles_data["mappings"]:
                if mapping.get("message_id") == str(message_id) and mapping.get("emoji") == emoji_str:
                    mapping["role_id"] = str(role_id)
                    existing = True
                    break

            if not existing:
                roles_data["mappings"].append({
                    "message_id": str(message_id),
                    "emoji": emoji_str,
                    "role_id": str(role_id),
                    "guild_id": message_info.get("guild_id")
                })

            with open(roles_file, 'w') as f:
                json.dump(roles_data, f, indent=2)

            # Append "emoji - description" to the message
            try:
                current_message = await bot.rest.fetch_message(channel_id, message_id)
                current_content = current_message.content or ""

                # Append the new line
                new_line = f"{emoji_str} - {description}"
                updated_content = current_content
                if updated_content:
                    updated_content += "\n" + new_line
                else:
                    updated_content = new_line

                # Edit the message
                await bot.rest.edit_message(channel_id, message_id, updated_content)
            except Exception as e:
                logger.error(f"Error updating message content: {e}")
                # Don't fail the command if message update fails, just log it

            await ctx.respond(
                f"{CHECK} Added role reaction!\n"
                f"Emoji: {emoji_str}\n"
                f"Role: <@&{role_id}>\n"
                f"Description: {description}\n"
                f"Users can now react to get this role automatically.",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error in add_role_reaction command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.respond(f"{CROSS} Error adding role reaction: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class RemoveRoleReactionCommand(lightbulb.SlashCommand, name="remove_role_reaction",
    description="Remove an emoji-role mapping from a roles message (admin only)",
    default_member_permissions=hikari.Permissions.MANAGE_MESSAGES):

    message_id = lightbulb.string('message_id', 'The message ID to remove reactions from')
    emoji = lightbulb.string('emoji', 'The emoji to remove (e.g., ✅ or :checkmark:)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Remove an emoji-role mapping from a roles message"""
        try:
            # Check if user is bot owner
            bot_owner_id = None
            try:
                owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
                if owner_id_str:
                    bot_owner_id = int(owner_id_str)
            except (ValueError, TypeError):
                pass

            if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
                await ctx.respond(f"{CROSS} Only the bot owner can use this command.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            message_id = int(self.message_id)
            emoji_str = self.emoji.strip()

            # Try to find the message
            roles_file = "reaction_roles.json"
            if not os.path.exists(roles_file):
                await ctx.respond(f"{CROSS} No roles messages found. Use `/setup_roles` first.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            with open(roles_file, 'r') as f:
                roles_data = json.load(f)

            # Find the message
            message_info = None
            for msg in roles_data.get("messages", []):
                if str(msg.get("message_id")) == str(message_id):
                    message_info = msg
                    break

            if not message_info:
                await ctx.respond(f"{CROSS} Message ID not found in roles messages.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            channel_id = int(message_info["channel_id"])

            # Find and remove the mapping
            mappings = roles_data.get("mappings", [])
            mapping_to_remove = None
            for mapping in mappings:
                if mapping.get("message_id") == str(message_id) and mapping.get("emoji") == emoji_str:
                    mapping_to_remove = mapping
                    break

            if not mapping_to_remove:
                await ctx.respond(f"{CROSS} No mapping found for this emoji on this message.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            role_id = mapping_to_remove.get("role_id")

            # Remove the mapping from the list
            roles_data["mappings"] = [m for m in mappings if m != mapping_to_remove]

            # Save the updated data
            with open(roles_file, 'w') as f:
                json.dump(roles_data, f, indent=2)

            # Remove the reaction from the message
            try:
                # Parse emoji for removal
                emoji_obj = None
                if emoji_str.startswith('<') and emoji_str.endswith('>'):
                    # Custom emoji format: <:name:id> or <a:name:id>
                    parts = emoji_str[1:-1].split(':')
                    if len(parts) == 3:
                        emoji_name = parts[1]
                        emoji_id = parts[2]
                        emoji_obj = f"{emoji_name}:{emoji_id}"
                elif emoji_str.startswith(':') and emoji_str.endswith(':'):
                    # Emoji name format: :emoji_name: - try to find it in the guild
                    emoji_name = emoji_str[1:-1]
                    try:
                        channel = await bot.rest.fetch_channel(channel_id)
                        if channel.guild_id:
                            guild = await bot.rest.fetch_guild(channel.guild_id)
                            for emoji in guild.get_emojis() or []:
                                if emoji.name == emoji_name:
                                    emoji_obj = f"{emoji.name}:{emoji.id}"
                                    break
                    except Exception as e:
                        logger.debug(f"Error searching for guild emoji: {e}")
                else:
                    # Unicode emoji
                    emoji_obj = emoji_str

                if emoji_obj:
                    # Remove the bot's reaction (we can't remove all reactions, but we can remove ours)
                    try:
                        # Get bot's user ID - use bot.me if available, otherwise skip
                        bot_user_id = None
                        try:
                            if hasattr(bot, 'me') and bot.me:
                                bot_user_id = bot.me.id
                        except:
                            pass

                        if bot_user_id:
                            await bot.rest.delete_reaction(channel_id, message_id, emoji_obj, bot_user_id)
                    except Exception as e:
                        logger.debug(f"Error removing bot reaction: {e}")
            except Exception as e:
                logger.error(f"Error removing reaction: {e}")

            # Remove the line from the message content
            try:
                current_message = await bot.rest.fetch_message(channel_id, message_id)
                current_content = current_message.content or ""

                # Remove the line that contains this emoji and description
                lines = current_content.split('\n')
                updated_lines = []
                for line in lines:
                    # Check if this line starts with the emoji (with optional whitespace)
                    line_stripped = line.strip()
                    if not line_stripped.startswith(emoji_str):
                        updated_lines.append(line)

                updated_content = '\n'.join(updated_lines).strip()

                # Edit the message
                if updated_content != current_content:
                    await bot.rest.edit_message(channel_id, message_id, updated_content)
            except Exception as e:
                logger.error(f"Error updating message content: {e}")
                # Don't fail the command if message update fails, just log it

            await ctx.respond(
                f"{CHECK} Removed role reaction!\n"
                f"Emoji: {emoji_str}\n"
                f"Role: <@&{role_id}>\n"
                f"The mapping has been removed and users will no longer get this role from reactions.",
                flags=hikari.MessageFlag.EPHEMERAL
            )
        except Exception as e:
            logger.error(f"Error in remove_role_reaction command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.respond(f"{CROSS} Error removing role reaction: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)