"""
Utility Commands

General utility commands:
- qr: Generate a QR code for adding a contact
- keygen: Generate a MeshCore keypair with a specific prefix
- help: Show all available commands
"""

from datetime import datetime
import asyncio
import hikari
import lightbulb
from concurrent.futures import ThreadPoolExecutor
from bot.core import client, logger, CROSS, CHECK, category_check, EMOJIS, pending_qr_selections
from bot.utils import (
    get_repeater_for_context,
    get_removed_nodes_file_for_context,
    is_node_removed,
    validate_hex_prefix,
)
from bot.helpers import generate_and_send_qr
import json
import os
import shutil

# Base path for resolving meshcore-utils (Rust keygen)
_MESHCORE_UTILS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "meshcore-utils")
_MC_KEYGEN_BINARY = os.path.join(_MESHCORE_UTILS_DIR, "target", "release", "mc-keygen")


def _find_mc_keygen():
    """Return path to mc-keygen binary, or None if not found."""
    if os.path.isfile(_MC_KEYGEN_BINARY):
        return _MC_KEYGEN_BINARY
    return shutil.which("mc-keygen")


async def _run_rust_keygen(prefix: str, timeout_sec: float = 90):
    """
    Run meshcore-utils mc-keygen with --json. Returns dict with public_key, private_key,
    matched_prefix, attempts, elapsed_secs (and keys_per_sec if elapsed_secs > 0), or None on failure/timeout.
    """
    binary = _find_mc_keygen()
    if not binary:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, prefix, "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=_MESHCORE_UTILS_DIR if os.path.isfile(_MC_KEYGEN_BINARY) else None,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return None
        if proc.returncode != 0:
            return None
        data = json.loads(stdout.decode())
        out = {
            "public_key": data["public_key"],
            "private_key": data["private_key"],
            "matched_prefix": data.get("matched_prefix", prefix),
            "attempts": data.get("attempts", 0),
            "elapsed_secs": data.get("elapsed_secs", 0.0),
        }
        if out["elapsed_secs"] > 0 and out["attempts"]:
            out["keys_per_sec"] = int(out["attempts"] / out["elapsed_secs"])
        else:
            out["keys_per_sec"] = 0
        return out
    except (OSError, ValueError, KeyError) as e:
        logger.debug(f"Rust keygen failed: {e}")
        return None


@client.register()
class QRCodeCommand(lightbulb.SlashCommand, name="qr",
    description="Generate a QR code for adding a contact", hooks=[category_check]):

    text = lightbulb.string('hex', 'Hex prefix (e.g., A1 or A1B2)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Generate a QR code for adding a contact"""
        try:
            # Check if hex parameter was provided
            if self.text is None:
                await ctx.respond("Please provide a hex prefix (e.g., `/qr A1` or `/qr A1B2`)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            ok, hex_prefix_or_err = validate_hex_prefix(self.text)
            if not ok:
                await ctx.respond(hex_prefix_or_err, flags=hikari.MessageFlag.EPHEMERAL)
                return
            hex_prefix = hex_prefix_or_err

            # Get repeaters
            repeaters = await get_repeater_for_context(ctx, hex_prefix)

            # Filter out removed nodes
            if repeaters:
                removed_nodes_file = await get_removed_nodes_file_for_context(ctx)
                repeaters = [r for r in repeaters if not is_node_removed(r, removed_nodes_file)]

            if not repeaters or len(repeaters) == 0:
                await ctx.respond(f"{CROSS} No repeater found with prefix {hex_prefix}.", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # If multiple repeaters found, show select menu
            if len(repeaters) > 1:
                # Create select menu options
                options = []
                for i, repeater in enumerate(repeaters):
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
                custom_id = f"qr_select_{hex_prefix}_{ctx.interaction.id}"

                # Store the matching repeaters for later retrieval
                pending_qr_selections[custom_id] = repeaters

                # Create select menu using hikari's builder
                action_row_builder = hikari.impl.MessageActionRowBuilder()

                # add_text_menu returns a TextSelectMenuBuilder
                select_menu_builder = action_row_builder.add_text_menu(
                    custom_id,  # custom_id must be positional
                    placeholder="Select a repeater to generate QR code",
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
                    f"Found {len(repeaters)} repeater(s) with prefix {hex_prefix}. Please select one:",
                    components=[action_row_builder],
                    flags=hikari.MessageFlag.EPHEMERAL
                )

                # Return early - the component listener will handle the selection
                return
            else:
                # Only one repeater found, generate QR code directly
                selected_repeater = repeaters[0]
                await generate_and_send_qr(selected_repeater, ctx)
        except Exception as e:
            logger.error(f"Error in qr command: {e}")
            await ctx.respond(f"Error generating QR code: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class KeygenCommand(lightbulb.SlashCommand, name="keygen",
    description="Generate a MeshCore keypair with a specific prefix", hooks=[category_check]):

    text = lightbulb.string('prefix', 'Hex prefix (e.g., F8A1)')

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Generate a MeshCore keypair with a specific prefix"""
        try:
            hex_prefix = self.text.upper().strip()

            # Validate hex format
            if len(hex_prefix) < 1 or len(hex_prefix) > 8:
                await ctx.respond("Invalid hex format. Prefix must be 1-8 hex characters (e.g., F8, F8A1)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Validate it's valid hex
            try:
                int(hex_prefix, 16)
            except ValueError:
                await ctx.respond("Invalid hex format. Prefix must contain only hex characters (0-9, A-F)", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # MeshCore reserves 00 and FF prefixes
            if hex_prefix.startswith("00") or hex_prefix.startswith("FF"):
                await ctx.respond("Prefix cannot start with 00 or FF (reserved by MeshCore).", flags=hikari.MessageFlag.EPHEMERAL)
                return

            # Send initial response
            await ctx.respond(f"🔑 Generating keypair with prefix `{hex_prefix}`... This may take a moment.", flags=hikari.MessageFlag.EPHEMERAL)

            # Prefer Rust mc-keygen (meshcore-utils) if available
            key_info = await _run_rust_keygen(hex_prefix, timeout_sec=90)
            if key_info:
                attempts = key_info.get("attempts", 0)
                elapsed = key_info.get("elapsed_secs", 0)
                kps = key_info.get("keys_per_sec", 0)
                elapsed_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{int(elapsed // 60)}m {elapsed % 60:.0f}s"
                stats = f"✓ Match found! {attempts:,} attempts in {elapsed_str} ({kps:,} keys/sec)"
                message = (
                    f"**Public key:**  `{key_info['public_key']}`\n"
                    f"**Private key:** `{key_info['private_key']}`"
                )
                await ctx.interaction.edit_initial_response(message)
                return

            # Fallback to Python meshcore_keygen
            try:
                from meshcore_keygen import VanityConfig, VanityMode, MeshCoreKeyGenerator
            except ImportError as e:
                logger.error(f"Error importing meshcore_keygen: {e}")
                await ctx.interaction.edit_initial_response(
                    f"{CROSS} No key generator available. Build the Rust keygen with `cargo build --release` in meshcore-utils/, or install the Python meshcore_keygen module."
                )
                return

            def generate_key():
                config = VanityConfig(
                    mode=VanityMode.PREFIX,
                    target_prefix=hex_prefix,
                    max_time=90,
                    max_iterations=100000000,
                    num_workers=2,
                    batch_size=100000,
                    health_check=False,
                    verbose=False
                )
                generator = MeshCoreKeyGenerator()
                return generator.generate_vanity_key(config)

            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                key_info = await loop.run_in_executor(executor, generate_key)

            if key_info:
                message = (
                    f"**Public key:**  `{key_info.public_hex}`\n"
                    f"**Private key:** `{key_info.private_hex}`"
                )
                await ctx.interaction.edit_initial_response(message)
            else:
                await ctx.interaction.edit_initial_response(f"{CROSS} Could not generate key with prefix `{hex_prefix}` within the time limit. Try a shorter prefix or try again.")
        except Exception as e:
            logger.error(f"Error in keygen command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await ctx.interaction.edit_initial_response(f"{CROSS} Error generating keypair: {str(e)}")
            except Exception as e:
                await ctx.respond(f"{CROSS} Error generating keypair: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


@client.register()
class HelpCommand(lightbulb.SlashCommand, name="help",
    description="Show all available commands", hooks=[category_check]):

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context):
        """Show all available commands"""
        try:
            help_message = """**Available Bot Commands:**

`/list` - Get list of active repeaters
`/offline` - Get list of offline repeaters (>3 days no advert)
`/dupes` - Get list of duplicate repeater prefixes
`/open` - Get list of unused hex keys
`/prefix <hex>` - Check if a hex prefix is available
`/rlist` - Get list of reserved repeaters
`/stats <hex>` - Get detailed stats of a repeater by hex prefix
`/qr <hex>` - Generate a QR code for adding a contact
`/reserve <prefix> <name>` - Reserve a hex prefix for a repeater
`/release <prefix>` - Release a hex prefix from the reserve list
`/remove <hex>` - Remove a repeater from the repeater list
`/claim <hex>` - Claim ownership of a repeater
`/unclaim <hex>` - Unclaim ownership of a repeater (owner or bot owner only)
`/keygen <prefix>` - Generate a MeshCore keypair with a specific prefix
`/help` - Show this help message
"""

            await ctx.respond(help_message)
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.respond("Error retrieving help information.", flags=hikari.MessageFlag.EPHEMERAL)