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
    get_prefix_length_for_context,
    validate_hex_prefix_for_category,
)
from bot.helpers import generate_and_send_qr
from meshcoredecoder.types.enums import PayloadType
from meshcoredecoder.utils.enum_names import get_route_type_name, get_device_role_name, get_payload_type_name
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


def load_secrets_from_file(secrets_file="secrets.json"):
    """Load channel secrets from secrets.json file"""
    secrets = {
        'channel_secrets': []
    }

    if not os.path.exists(secrets_file):
        return secrets

    try:
        with open(secrets_file, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict):
                # Load channel_secrets
                if 'channel_secrets' in data:
                    channel_secrets = data['channel_secrets']
                    if isinstance(channel_secrets, list):
                        # Clean up hex strings (remove spaces, 0x prefixes)
                        cleaned_secrets = []
                        for secret in channel_secrets:
                            if isinstance(secret, str):
                                cleaned = secret.replace(' ', '').replace('0x', '').replace('0X', '')
                                cleaned_secrets.append(cleaned)
                        secrets['channel_secrets'] = cleaned_secrets
    except json.JSONDecodeError as e:
        logger.warning(f"Error parsing {secrets_file}: {e}")
    except Exception as e:
        logger.warning(f"Error loading {secrets_file}: {e}")

    return secrets


def save_secrets_to_file(secrets, secrets_file="secrets.json"):
    """Save channel secrets to secrets.json file"""
    try:
        with open(secrets_file, 'w') as f:
            json.dump(secrets, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {secrets_file}: {e}")
        return False


async def _format_payload_details(payload, message_parts):
    """Format payload details matching cli.py show_payload_details function"""
    payload_type = payload.type if hasattr(payload, 'type') else None
    message_parts.append(f"**Payload Type:** {get_payload_type_name(payload_type) if payload_type else 'Unknown'}")

    if hasattr(payload, 'version'):
        message_parts.append(f"**Payload Version:** {payload.version.value if hasattr(payload.version, 'value') else payload.version}")
    if hasattr(payload, 'is_valid'):
        valid_icon = CHECK if payload.is_valid else CROSS
        message_parts.append(f"{valid_icon} **Valid:** {payload.is_valid}")

    if hasattr(payload, 'errors') and payload.errors:
        message_parts.append(f"**Errors:**")
        for error in payload.errors:
            message_parts.append(f"  {CROSS} {error}")

    # Handle different payload types (matching cli.py)
    if payload_type == PayloadType.Advert:
        advert = payload
        message_parts.append(f"**Public Key:** {advert.public_key}")
        if hasattr(advert, 'app_data') and advert.app_data:
            device_role = advert.app_data.get("device_role")
            if device_role is not None:
                message_parts.append(f"**Device Role:** {get_device_role_name(device_role)}")

            if advert.app_data.get('name'):
                message_parts.append(f"**Device Name:** {advert.app_data['name']}")

            if advert.app_data.get('location'):
                loc = advert.app_data['location']
                message_parts.append(f"**Location:** {loc['latitude']}, {loc['longitude']}")

            if advert.app_data.get('battery_voltage') is not None:
                message_parts.append(f"**Battery Voltage:** {advert.app_data['battery_voltage']} V")

        if hasattr(advert, 'timestamp') and advert.timestamp:
            message_parts.append(f"**Timestamp:** {datetime.fromtimestamp(advert.timestamp).isoformat()}")
        if hasattr(advert, 'signature') and advert.signature:
            message_parts.append(f"**Signature:** {advert.signature}")

        # Signature verification status
        if hasattr(advert, 'signature_valid') and advert.signature_valid is not None:
            if advert.signature_valid:
                message_parts.append(f"**Signature Status:** {CHECK} Valid Ed25519 signature")
            else:
                message_parts.append(f"**Signature Status:** {CROSS} Invalid Ed25519 signature")
                if hasattr(advert, 'signature_error') and advert.signature_error:
                    message_parts.append(f"**Signature Error:** {advert.signature_error}")
        else:
            message_parts.append(f"**Signature Status:** ⚠️ Not verified")

        if hasattr(advert, 'app_data') and advert.app_data:
            message_parts.append(f"\n**App Data:**")
            device_role = advert.app_data.get("device_role")
            if device_role is not None:
                message_parts.append(f"  **Device Role:** {get_device_role_name(device_role)}")
            if advert.app_data.get('name'):
                message_parts.append(f"  **Device Name:** {advert.app_data['name']}")
            if advert.app_data.get('location'):
                loc = advert.app_data['location']
                message_parts.append(f"  **Location:** {loc['latitude']}, {loc['longitude']}")
            if advert.app_data.get('battery_voltage') is not None:
                message_parts.append(f"  **Battery Voltage:** {advert.app_data['battery_voltage']} V")

    elif payload_type == PayloadType.GroupText:
        group_text = payload
        if hasattr(group_text, 'channel_hash'):
            message_parts.append(f"**Channel Hash:** {group_text.channel_hash} (0x{group_text.channel_hash})")
        if hasattr(group_text, 'cipher_mac'):
            message_parts.append(f"**Cipher MAC:** {group_text.cipher_mac}")
        if hasattr(group_text, 'ciphertext_length'):
            message_parts.append(f"**Ciphertext Length:** {group_text.ciphertext_length} bytes")

        if hasattr(group_text, 'decrypted') and group_text.decrypted:
            message_parts.append(f"\n**🔓 Decrypted Message:**")
            decrypted = group_text.decrypted
            if decrypted.get('timestamp'):
                message_parts.append(f"**Timestamp:** {datetime.fromtimestamp(decrypted.get('timestamp', 0)).isoformat()}")

            flags = decrypted.get('flags', 0)
            txt_type = (flags >> 2) & 0x3F
            attempt = flags & 0x03
            message_parts.append(f"**Text Type:** {txt_type} (attempt: {attempt})")

            if decrypted.get('sender'):
                message_parts.append(f"**Sender:** {decrypted['sender']}")
            if decrypted.get('message'):
                message_parts.append(f"**Message:** {decrypted['message']}")
        else:
            message_parts.append("\n🔒 **Encrypted** (channel shared key required)")
            if hasattr(group_text, 'ciphertext'):
                message_parts.append(f"**Ciphertext:** {group_text.ciphertext[:64]}...")
            if hasattr(group_text, 'channel_hash'):
                message_parts.append(f"**Note:** To decrypt, provide channel shared key for hash 0x{group_text.channel_hash}")

    elif payload_type == PayloadType.Request:
        request = payload
        if hasattr(request, 'destination_hash'):
            message_parts.append(f"**Destination Hash:** {request.destination_hash}")
        if hasattr(request, 'source_hash'):
            message_parts.append(f"**Source Hash:** {request.source_hash}")

        if hasattr(request, 'decrypted') and request.decrypted:
            message_parts.append(f"**🔓 Decrypted Request:**")
            decrypted = request.decrypted
            if decrypted.get('timestamp'):
                message_parts.append(f"**Timestamp:** {datetime.fromtimestamp(decrypted['timestamp']).isoformat()}")

            if decrypted.get('request_type_name'):
                request_type_name = decrypted["request_type_name"]
                request_type_val = decrypted["request_type"]
                message_parts.append(f"\n**📋 Request Type:** **{request_type_name}** (0x{request_type_val:02x})")

            if decrypted.get('request_data'):
                req_data = decrypted['request_data']
                message_parts.append(f"\n**Request Data:**")
                for key, value in req_data.items():
                    if key not in ['description', 'raw', 'error']:
                        message_parts.append(f"  **{key}:** {value}")
                if req_data.get('description'):
                    message_parts.append(f"  **Description:** {req_data['description']}")
                if req_data.get('error'):
                    message_parts.append(f"  **⚠️ Error:** {req_data['error']}")
        else:
            message_parts.append("🔒 **Encrypted** (no key available)")
            if hasattr(request, 'ciphertext'):
                message_parts.append(f"**Ciphertext:** {request.ciphertext[:32]}...")
            message_parts.append(f"**Request Type:** Unknown (decryption required)")

    elif payload_type == PayloadType.Response:
        response = payload
        if hasattr(response, 'destination_hash'):
            message_parts.append(f"**Destination Hash:** {response.destination_hash}")
        if hasattr(response, 'source_hash'):
            message_parts.append(f"**Source Hash:** {response.source_hash}")

        if hasattr(response, 'decrypted') and response.decrypted:
            message_parts.append(f"**🔓 Decrypted Response:**")
            decrypted = response.decrypted
            if decrypted.get('tag'):
                message_parts.append(f"**Tag:** {decrypted.get('tag', 'N/A')}")

            content = decrypted.get('content', {})
            content_type = content.get('type', 'unknown')

            if content_type == 'neighbours':
                message_parts.append(f"\n**📋 Response Type:** Neighbours")
                if content.get('sender_timestamp'):
                    message_parts.append(f"**Sender Timestamp:** {datetime.fromtimestamp(content.get('sender_timestamp', 0)).isoformat()}")
                message_parts.append(f"**Total Neighbours:** {content.get('neighbours_count', 0)}")
                message_parts.append(f"**Results in Response:** {content.get('results_count', 0)}")

                neighbors = content.get('neighbors', [])
                if neighbors:
                    message_parts.append(f"\n**Neighbors:**")
                    for i, neighbor in enumerate(neighbors, 1):
                        message_parts.append(f"  {i}. Pubkey Prefix: {neighbor.get('pubkey_prefix', 'N/A')}")
                        message_parts.append(f"     Heard {neighbor.get('heard_seconds_ago', 0)}s ago")
                        snr_value = neighbor.get("snr", 0) / 4.0
                        message_parts.append(f"     SNR: {snr_value:.2f} dB")

            elif content_type == 'telemetry':
                message_parts.append(f"\n**📋 Response Type:** Telemetry Data")
                tag = content.get('tag', decrypted.get('tag', 0))
                if tag:
                    message_parts.append(f"**Tag:** {tag} ({datetime.fromtimestamp(tag).isoformat() if tag > 0 else 'N/A'})")
                telemetry_hex = content.get('telemetry_data', '')
                if telemetry_hex:
                    from meshcoredecoder.utils.hex import hex_to_bytes
                    telemetry_bytes = hex_to_bytes(telemetry_hex)
                    message_parts.append(f"**Telemetry Data Length:** {len(telemetry_bytes)} bytes")
                    message_parts.append(f"**Telemetry Data (Hex):** {telemetry_hex[:64]}...")
                else:
                    message_parts.append(f"**Telemetry Data:** N/A")

            elif content_type == 'stats':
                message_parts.append(f"\n**📋 Response Type:** Stats")
                message_parts.append(f"**Tag:** {decrypted.get('tag', 'N/A')}")
                stats_data = content.get('stats_data', '')
                if stats_data:
                    from meshcoredecoder.utils.hex import hex_to_bytes
                    stats_bytes = hex_to_bytes(stats_data)
                    if len(stats_bytes) >= 40:
                        # Parse stats (simplified version - full parsing in cli.py is very long)
                        message_parts.append(f"**Stats Data Length:** {len(stats_bytes)} bytes")
                        message_parts.append(f"**Stats Data (Hex):** {stats_data[:64]}...")
                    else:
                        message_parts.append(f"**Stats Data Length:** {len(stats_bytes)} bytes")
                        message_parts.append(f"**Stats Data (Hex):** {stats_data}")

            elif content_type == 'access_list':
                message_parts.append(f"\n**📋 Response Type:** Access List")
                tag = content.get('tag', 0)
                if tag > 0:
                    message_parts.append(f"**Tag:** {tag} ({datetime.fromtimestamp(tag).isoformat()})")
                entries = content.get('entries', [])
                if entries:
                    valid_entries = [e for e in entries if e.get('permissions', 0) != 0]
                    if valid_entries:
                        message_parts.append(f"\n**Access List Entries:** ({len(valid_entries)} valid)")
                        for i, entry in enumerate(valid_entries, 1):
                            permissions = entry.get('permissions', 0)
                            role = permissions & 0x03
                            features = permissions >> 2
                            role_name = {0: 'No access', 1: 'Guest', 2: 'Read-only', 3: 'Admin'}.get(role, 'Unknown')
                            message_parts.append(f"  {i}. Pubkey Prefix: {entry.get('pubkey_prefix', 'N/A')}")
                            message_parts.append(f"     Permissions: 0x{permissions:02x} (Role: {role_name}, Features: 0x{features:02x})")
                else:
                    message_parts.append(f"\n**Note:** No access list entries found.")

            else:
                message_parts.append(f"\n**Response Content:**")
                message_parts.append(f"**Type:** {content_type}")
                if content.get('raw'):
                    message_parts.append(f"**Raw Data:** {content['raw'][:64]}...")
        else:
            message_parts.append("🔒 **Encrypted** (no key available)")
            if hasattr(response, 'ciphertext'):
                message_parts.append(f"**Ciphertext:** {response.ciphertext[:32]}...")

    elif payload_type == PayloadType.TextMessage:
        text_msg = payload
        if hasattr(text_msg, 'destination_hash'):
            message_parts.append(f"**Destination Hash:** {text_msg.destination_hash} (0x{text_msg.destination_hash})")
        if hasattr(text_msg, 'source_hash'):
            message_parts.append(f"**Source Hash:** {text_msg.source_hash} (0x{text_msg.source_hash})")
        if hasattr(text_msg, 'cipher_mac'):
            message_parts.append(f"**Cipher MAC:** {text_msg.cipher_mac}")
        if hasattr(text_msg, 'ciphertext_length'):
            message_parts.append(f"**Ciphertext Length:** {text_msg.ciphertext_length} bytes")

        if hasattr(text_msg, 'decrypted') and text_msg.decrypted:
            message_parts.append(f"\n**🔓 Decrypted Message:**")
            decrypted = text_msg.decrypted
            if decrypted.get('timestamp'):
                message_parts.append(f"**Timestamp:** {datetime.fromtimestamp(decrypted.get('timestamp', 0)).isoformat()}")

            txt_type = decrypted.get('txt_type', 0)
            attempt = decrypted.get('attempt', 0)
            txt_type_names = {0: 'Plain Text', 1: 'CLI Command', 2: 'Signed Plain Text'}
            txt_type_name = txt_type_names.get(txt_type, f'Unknown ({txt_type})')
            message_parts.append(f"**Text Type:** {txt_type_name} (0x{txt_type:02x})")
            message_parts.append(f"**Attempt:** {attempt}")

            if txt_type == 0x02 and decrypted.get('sender_pubkey_prefix'):
                message_parts.append(f"**Sender Pubkey Prefix:** {decrypted['sender_pubkey_prefix']}")

            if decrypted.get("message"):
                message_parts.append(f"**Message:** {decrypted['message']}")
        else:
            message_parts.append("\n🔒 **Encrypted** (ECDH keys required)")
            if hasattr(text_msg, 'ciphertext'):
                message_parts.append(f"**Ciphertext:** {text_msg.ciphertext[:64]}...")
            message_parts.append(f"**Note:** To decrypt, provide --node-key and --peer-key (or --shared-secret)")

    elif payload_type == PayloadType.Ack:
        ack = payload
        if hasattr(ack, 'checksum'):
            checksum_hex = ack.checksum.upper()
            try:
                checksum_int = int(checksum_hex, 16)
                message_parts.append(f"**Checksum:** 0x{checksum_hex} ({checksum_int:,})")
                message_parts.append(f"**Description:** CRC checksum of message timestamp, text, and sender pubkey")
            except ValueError:
                message_parts.append(f"**Checksum:** {ack.checksum}")

    elif payload_type == PayloadType.Trace:
        trace = payload
        if hasattr(trace, 'trace_tag'):
            message_parts.append(f"**Trace Tag:** {trace.trace_tag} (0x{trace.trace_tag})")
        if hasattr(trace, 'auth_code'):
            message_parts.append(f"**Auth Code:** {trace.auth_code}")
        if hasattr(trace, 'flags') and trace.flags is not None:
            message_parts.append(f"**Flags:** 0x{trace.flags:02x}")

        if hasattr(trace, 'path_hashes') and trace.path_hashes and len(trace.path_hashes) > 0:
            message_parts.append(f"**Path Hashes:** {' → '.join(trace.path_hashes)}")

        if hasattr(trace, 'snr_values') and trace.snr_values and len(trace.snr_values) > 0:
            message_parts.append(f"\n**SNR Values Along Path:**")
            path_for_display = trace.path_hashes if hasattr(trace, 'path_hashes') and trace.path_hashes else None
            for i, snr in enumerate(trace.snr_values):
                hop_info = f'Hop {i+1}'
                if path_for_display and i < len(path_for_display):
                    hop_info = f'Hop {i+1} (Node {path_for_display[i]})'
                message_parts.append(f"  {hop_info}: {snr:.1f} dB")

            if len(trace.snr_values) > 1:
                avg_snr = sum(trace.snr_values) / len(trace.snr_values)
                min_snr = min(trace.snr_values)
                max_snr = max(trace.snr_values)
                message_parts.append(f"\n**SNR Summary:**")
                message_parts.append(f"  Average: {avg_snr:.1f} dB")
                message_parts.append(f"  Min: {min_snr:.1f} dB")
                message_parts.append(f"  Max: {max_snr:.1f} dB")

    else:
        # Generic fallback for other payload types
        message_parts.append(f"\n**=== Payload Data ===")
        attrs = [attr for attr in dir(payload) if not attr.startswith('_') and not callable(getattr(payload, attr, None))]
        for attr in attrs:
            try:
                value = getattr(payload, attr)
                if value is not None and attr not in ['type', 'version', 'is_valid', 'errors']:
                    if isinstance(value, list) and len(value) > 0:
                        if len(value) <= 5:
                            message_parts.append(f"**{attr}:** {value}")
                        else:
                            message_parts.append(f"**{attr}:** [{len(value)} items] {value[:3]} ... {value[-2:]}")
                    elif isinstance(value, dict):
                        message_parts.append(f"**{attr}:** {len(value)} keys")
                    elif isinstance(value, str) and len(value) > 64:
                        message_parts.append(f"**{attr}:** {value[:64]}...")
                    else:
                        message_parts.append(f"**{attr}:** {value}")
            except Exception:
                pass


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

            prefix_length = await get_prefix_length_for_context(ctx)
            ok, hex_prefix_or_err = validate_hex_prefix_for_category(self.text, prefix_length)
            if not ok:
                await ctx.respond(hex_prefix_or_err, flags=hikari.MessageFlag.EPHEMERAL)
                return
            hex_prefix = hex_prefix_or_err

            # Get repeaters
            repeaters = await get_repeater_for_context(ctx, hex_prefix)

            # Filter out removed nodes (category-specific)
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

            key_info = None

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


# @client.register()
# class DecodeCommand(lightbulb.SlashCommand, name="decode",
#     description="Decode a raw packet hex string", hooks=[category_check]):

#     text = lightbulb.string('hex', 'Raw packet hex string')

#     @lightbulb.invoke
#     async def invoke(self, ctx: lightbulb.Context):
#         """Decode a raw packet hex string"""
#         try:
#             # Check if hex parameter was provided
#             if self.text is None:
#                 await ctx.respond("Please provide a raw packet hex string (e.g., `/decode A1B2C3D4...`)", flags=hikari.MessageFlag.EPHEMERAL)
#                 return

#             raw_hex = self.text.strip()

#             # Remove common hex prefixes/separators
#             raw_hex = raw_hex.replace('0x', '').replace('0X', '').replace(' ', '').replace('-', '').replace(':', '')

#             # Validate hex format
#             if not raw_hex:
#                 await ctx.respond("Empty hex string provided.", flags=hikari.MessageFlag.EPHEMERAL)
#                 return

#             if not all(c in '0123456789ABCDEFabcdef' for c in raw_hex):
#                 await ctx.respond("Invalid hex format. Please provide a valid hex string.", flags=hikari.MessageFlag.EPHEMERAL)
#                 return

#             # Import decoder
#             try:
#                 from meshcoredecoder import MeshCoreDecoder
#                 from meshcoredecoder.crypto import MeshCoreKeyStore
#                 from meshcoredecoder.types.crypto import DecryptionOptions
#             except ImportError as e:
#                 logger.error(f"Error importing meshcoredecoder: {e}")
#                 await ctx.respond(f"{CROSS} Error: Could not import decoder module.", flags=hikari.MessageFlag.EPHEMERAL)
#                 return

#             # Load channel secrets from secrets.json
#             secrets = load_secrets_from_file()
#             key_store = None
#             options = None

#             if secrets.get('channel_secrets'):
#                 # Create key store with channel secrets
#                 key_store_data = {
#                     'channel_secrets': secrets['channel_secrets']
#                 }
#                 key_store = MeshCoreKeyStore(key_store_data)
#                 options = DecryptionOptions(key_store=key_store)

#             # Decode the packet with verification
#             try:
#                 if options:
#                     packet = MeshCoreDecoder.decode_with_verification(raw_hex, options)
#                 else:
#                     packet = MeshCoreDecoder.decode_with_verification(raw_hex)
#             except Exception as e:
#                 await ctx.respond(f"{CROSS} Error decoding packet: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)
#                 return

#             # Build response message matching cli.py format
#             message_parts = []
#             message_parts.append("**=== MeshCore Packet Analysis ===**\n")

#             if not packet.is_valid:
#                 message_parts.append(f"{CROSS} **Invalid Packet**")
#                 if hasattr(packet, 'errors') and packet.errors:
#                     for error in packet.errors:
#                         message_parts.append(f"   {error}")
#             else:
#                 message_parts.append(f"{CHECK} **Valid Packet**")

#             # Packet-level information (matching cli.py)
#             if hasattr(packet, 'message_hash') and packet.message_hash:
#                 message_parts.append(f"**Message Hash:** {packet.message_hash}")
#             if hasattr(packet, 'route_type'):
#                 message_parts.append(f"**Route Type:** {get_route_type_name(packet.route_type)}")
#             if hasattr(packet, 'payload_type'):
#                 payload_type_name = get_payload_type_name(packet.payload_type) if packet.is_valid else 'Invalid'
#                 message_parts.append(f"**Payload Type:** {payload_type_name}")
#             if hasattr(packet, 'total_bytes'):
#                 message_parts.append(f"**Total Bytes:** {packet.total_bytes}")

#             if hasattr(packet, 'path') and packet.path and len(packet.path) > 0:
#                 message_parts.append(f"**Path:** {' → '.join(packet.path)}")

#             # Show payload details (matching cli.py show_payload_details function)
#             decoded = packet.payload.get('decoded') if packet.payload else None
#             if decoded:
#                 message_parts.append(f"\n**=== Payload Details ===**")
#                 await _format_payload_details(decoded, message_parts)

#             if not packet.is_valid:
#                 message_parts.append(f"\n{CROSS} Packet validation failed")

#             message = "\n".join(message_parts)
#             await ctx.respond(message, flags=hikari.MessageFlag.EPHEMERAL)

#         except Exception as e:
#             logger.error(f"Error in decode command: {e}")
#             import traceback
#             logger.error(traceback.format_exc())
#             await ctx.respond(f"{CROSS} Error decoding packet: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


# @client.register()
# class SecretCommand(lightbulb.SlashCommand, name="secret",
#     description="Manage channel secrets for decrypting GroupText payloads"):

#     secret = lightbulb.string('key', 'Channel secret hex key (required for add/remove)', default=None)
#     action = lightbulb.string('action', 'Action: add, list, or remove', default="add")

#     @lightbulb.invoke
#     async def invoke(self, ctx: lightbulb.Context):
#         """Manage channel secrets for decrypting GroupText payloads"""
#         try:
#             # Check if user is bot owner
#             bot_owner_id = None
#             try:
#                 owner_id_str = config.get("discord", "bot_owner_id", fallback=None)
#                 if owner_id_str:
#                     bot_owner_id = int(owner_id_str)
#             except (ValueError, AttributeError):
#                 pass

#             if not ctx.member or not bot_owner_id or ctx.member.user.id != bot_owner_id:
#                 await ctx.respond(f"{CROSS} Only the bot owner can manage secrets.", flags=hikari.MessageFlag.EPHEMERAL)
#                 return

#             action = self.action.lower() if self.action else "add"
#             secrets_file = "secrets.json"

#             if action == "add":
#                 if not self.secret:
#                     await ctx.respond("Please provide a channel secret hex key to add.", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 # Clean up hex string
#                 secret_hex = self.secret.strip().replace(' ', '').replace('0x', '').replace('0X', '').replace('-', '').replace(':', '')

#                 # Validate hex format
#                 if not secret_hex:
#                     await ctx.respond("Empty secret provided.", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 if not all(c in '0123456789ABCDEFabcdef' for c in secret_hex):
#                     await ctx.respond("Invalid hex format. Please provide a valid hex string.", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 # Load existing secrets
#                 secrets = load_secrets_from_file(secrets_file)
#                 if 'channel_secrets' not in secrets:
#                     secrets['channel_secrets'] = []

#                 # Check if secret already exists
#                 if secret_hex.upper() in [s.upper() for s in secrets['channel_secrets']]:
#                     await ctx.respond(f"{CROSS} This secret already exists in the secrets file.", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 # Add new secret
#                 secrets['channel_secrets'].append(secret_hex.upper())

#                 # Save to file
#                 if save_secrets_to_file(secrets, secrets_file):
#                     await ctx.respond(f"{CHECK} Channel secret added successfully. ({len(secrets['channel_secrets'])} total secrets)", flags=hikari.MessageFlag.EPHEMERAL)
#                 else:
#                     await ctx.respond(f"{CROSS} Error saving secret to file.", flags=hikari.MessageFlag.EPHEMERAL)

#             elif action == "list":
#                 # Load secrets
#                 secrets = load_secrets_from_file(secrets_file)
#                 channel_secrets = secrets.get('channel_secrets', [])

#                 if not channel_secrets:
#                     await ctx.respond("No channel secrets found in secrets.json", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 # Show count and partial info (for security, don't show full keys)
#                 message_parts = [f"**Channel Secrets:** {len(channel_secrets)} total\n"]
#                 for i, secret in enumerate(channel_secrets, 1):
#                     # Show first 8 and last 8 characters for identification
#                     if len(secret) > 16:
#                         masked = f"{secret[:8]}...{secret[-8:]}"
#                     else:
#                         masked = secret[:8] + "..."
#                     message_parts.append(f"{i}. `{masked}`")

#                 await ctx.respond("\n".join(message_parts), flags=hikari.MessageFlag.EPHEMERAL)

#             elif action == "remove":
#                 if not self.secret:
#                     await ctx.respond("Please provide a channel secret hex key to remove (or use partial match).", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 # Clean up hex string
#                 secret_hex = self.secret.strip().replace(' ', '').replace('0x', '').replace('0X', '').replace('-', '').replace(':', '').upper()

#                 # Load existing secrets
#                 secrets = load_secrets_from_file(secrets_file)
#                 if 'channel_secrets' not in secrets:
#                     secrets['channel_secrets'] = []

#                 # Find and remove matching secret
#                 original_count = len(secrets['channel_secrets'])
#                 secrets['channel_secrets'] = [s for s in secrets['channel_secrets'] if secret_hex not in s.upper()]

#                 if len(secrets['channel_secrets']) == original_count:
#                     await ctx.respond(f"{CROSS} Secret not found in secrets file.", flags=hikari.MessageFlag.EPHEMERAL)
#                     return

#                 # Save to file
#                 if save_secrets_to_file(secrets, secrets_file):
#                     removed_count = original_count - len(secrets['channel_secrets'])
#                     await ctx.respond(f"{CHECK} Removed {removed_count} secret(s). ({len(secrets['channel_secrets'])} remaining)", flags=hikari.MessageFlag.EPHEMERAL)
#                 else:
#                     await ctx.respond(f"{CROSS} Error saving secrets file.", flags=hikari.MessageFlag.EPHEMERAL)

#             else:
#                 await ctx.respond(f"{CROSS} Invalid action. Use 'add', 'list', or 'remove'.", flags=hikari.MessageFlag.EPHEMERAL)

#         except Exception as e:
#             logger.error(f"Error in secret command: {e}")
#             import traceback
#             logger.error(traceback.format_exc())
#             await ctx.respond(f"{CROSS} Error managing secrets: {str(e)}", flags=hikari.MessageFlag.EPHEMERAL)


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

-# Version: 1.6.0
"""

            await ctx.respond(help_message)
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await ctx.respond("Error retrieving help information.", flags=hikari.MessageFlag.EPHEMERAL)