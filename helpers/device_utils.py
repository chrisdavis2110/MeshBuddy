"""
Device utilities for device type extraction and filtering.
"""

import logging
from datetime import datetime
from .data_utils import load_data_from_json

logger = logging.getLogger(__name__)


def is_within_window(contact, min_days=0, max_days=7):
    """Check if a contact was last seen within a specific day window (e.g., 2-8 days ago)"""
    try:
        last_seen_str = contact.get('last_seen', '')
        if not last_seen_str:
            return False

        # Parse the ISO format timestamp
        last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))

        # Calculate how many days ago it was seen
        days_ago = (datetime.now(last_seen.tzinfo) - last_seen).days

        # Check if it's within the window (2-8 days ago)
        return min_days <= days_ago <= max_days
    except (ValueError, TypeError) as e:
        logger.debug(f"Error parsing last_seen timestamp '{last_seen_str}': {e}")
        return False


def extract_device_types(data=None, device_types=None, days=7, data_dir=None):
    """
    Extract specific device types from nodes data

    Args:
        data: Pre-loaded data (optional). If None, loads from nodes.json
        device_types (list): List of device types to extract. Options:
            - 'repeaters': device_role == 2
            - 'companions': device_role == 1
            - 'room_servers': device_role == 3
            If None, extracts all three types
        days (int): Maximum days since last seen (default: 7)
        data_dir (str): Directory containing nodes.json (optional)

    Returns:
        dict: Dictionary with device types as keys and lists of devices as values
    """
    # Load data if not provided
    if data is None:
        data = load_data_from_json(data_dir=data_dir)

    if data is None:
        print("No data found in nodes.json")
        return None

    # Extract contacts from the loaded data
    contacts = data.get("data", []) if isinstance(data, dict) else data

    if not isinstance(contacts, list):
        print("No valid contact data found")
        return None

    # Default to all device types if none specified
    if device_types is None:
        device_types = ['repeaters', 'companions', 'room_servers']

    result = {device_type: [] for device_type in device_types}

    for contact in contacts:
        if not isinstance(contact, dict):
            continue

        # Check if device is within the specified time window
        if not is_within_window(contact, min_days=0, max_days=days):
            continue

        # Check device type and add to appropriate list
        if 'repeaters' in device_types and contact.get('device_role') == 2:
            result['repeaters'].append(contact)
        elif 'companions' in device_types and contact.get('device_role') == 1:
            result['companions'].append(contact)
        elif 'room_servers' in device_types and contact.get('device_role') == 3:
            result['room_servers'].append(contact)

    return result


def get_companion_list(days=7, data_dir=None):
    """Get list of companions using the new extraction function"""
    devices = extract_device_types(device_types=['companions'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    companions = devices['companions']
    print(f"Found {len(companions)} companions (seen within last {days} days):")

    companion_list = []
    for contact in companions:
        prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
        name = contact.get('name', 'Unknown')
        print(f"{prefix}: {name}")
        companion_list.append(f"{prefix}: {name}")

    return companion_list


def get_room_server_list(days=7, data_dir=None):
    """Get list of room servers using the new extraction function"""
    devices = extract_device_types(device_types=['room_servers'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    room_servers = devices['room_servers']
    print(f"Found {len(room_servers)} room servers (seen within last {days} days):")

    room_server_list = []
    for contact in room_servers:
        prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
        name = contact.get('name', 'Unknown')
        print(f"{prefix}: {name}")
        room_server_list.append(f"{prefix}: {name}")

    return room_server_list


def get_repeater_list(days=7, data_dir=None):
    """Get list of repeaters using the new extraction function"""
    devices = extract_device_types(device_types=['repeaters'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    repeaters = devices['repeaters']
    print(f"Found {len(repeaters)} repeaters (seen within last {days} days):")

    repeater_list = []
    for contact in repeaters:
        prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
        name = contact.get('name', 'Unknown')
        print(f"{prefix}: {name}")
        repeater_list.append(f"{prefix}: {name}")

    return repeater_list


def get_repeater_duplicates(days=7, data_dir=None):
    """Get repeater duplicates using the new extraction function.
    Only shows duplicates if repeaters have the same key prefix but different names.
    If repeaters have the same name, they are ignored."""
    devices = extract_device_types(device_types=['repeaters'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    repeaters = devices['repeaters']

    # Count prefixes to find duplicates
    prefix_count = {}
    for contact in repeaters:
        prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
        prefix_count[prefix] = prefix_count.get(prefix, 0) + 1

    # Find prefixes that appear more than once
    duplicate_prefixes = [prefix for prefix, count in prefix_count.items() if count > 1]

    if duplicate_prefixes:
        duplicate_list = []
        actual_duplicates_found = 0

        for prefix in duplicate_prefixes:
            # Get all repeaters with this prefix
            prefix_repeaters = [contact for contact in repeaters
                              if contact.get('public_key', '')[:2] == prefix]

            # Check if repeaters have different names
            names = [contact.get('name', 'Unknown') for contact in prefix_repeaters]
            unique_names = set(names)

            # Only consider it a duplicate if there are different names
            if len(unique_names) > 1:
                actual_duplicates_found += 1
                print(f"\nPrefix '{prefix}' ({len(prefix_repeaters)} repeaters):")
                for contact in prefix_repeaters:
                    name = contact.get('name', 'Unknown')
                    repeater_info = f"{prefix}: {name}"
                    print(f"  - {repeater_info}")
                    duplicate_list.append(repeater_info)
            else:
                # All repeaters with this prefix have the same name - ignore
                print(f"\nPrefix '{prefix}' ({len(prefix_repeaters)} repeaters with same name '{names[0]}' - ignoring)")

        if actual_duplicates_found > 0:
            print(f"\nFound {actual_duplicates_found} duplicate prefixes:")
        else:
            print("\nNo duplicate prefixes found")
            duplicate_list = []
    else:
        print("No duplicate prefixes found")
        duplicate_list = []

    return duplicate_list


def get_repeater_offline(days=8, data_dir=None):
    """Show repeaters that haven't been heard in 2 days"""
    # Get repeaters that are 2-8 days old
    devices = extract_device_types(device_types=['repeaters'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    repeaters = devices['repeaters']

    # Filter to only those that are 2+ days old
    offline_data = [contact for contact in repeaters
                    if is_within_window(contact, min_days=2, max_days=days)]

    if offline_data:
        print(f"Found {len(offline_data)} offline repeaters (last seen 2-{days} days ago):")

        offline_list = []
        for contact in offline_data:
            prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
            name = contact.get('name', 'Unknown')
            last_seen = contact.get('last_seen', 'Unknown')

            # Format the last_seen timestamp for display
            try:
                if last_seen != 'Unknown':
                    last_seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    days_ago = (datetime.now(last_seen_dt.tzinfo) - last_seen_dt).days
                    last_seen_formatted = f"{days_ago} days ago"
                else:
                    last_seen_formatted = "Unknown"
            except Exception:
                last_seen_formatted = "Invalid timestamp"

            repeater_info = f"{prefix}: {name} (last seen: {last_seen_formatted})"
            print(f"- {repeater_info}")
            offline_list.append(repeater_info)

        return offline_list
    else:
        print(f"No offline repeaters found (no repeaters last seen 2-{days} days ago)")
        return []


def get_unused_keys(days=7, data_dir=None):
    """Show which hex keys from 00 to FF are not currently being used"""
    devices = extract_device_types(device_types=['repeaters'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    repeaters = devices['repeaters']

    # Get all currently used prefixes
    used_keys = set()
    for contact in repeaters:
        if contact.get('public_key'):
            prefix = contact.get('public_key', '')[:2]
            used_keys.add(prefix.upper())  # Convert to uppercase for consistency

    # Generate all possible hex keys from 00 to FF
    all_possible_keys = set()
    for i in range(256):  # 0 to 255 (0x00 to 0xFF)
        hex_key = f"{i:02X}"  # Format as uppercase hex with leading zero
        all_possible_keys.add(hex_key)

    # Find unused keys
    unused_keys = all_possible_keys - used_keys

    if unused_keys:
        # Sort the unused keys for consistent output
        sorted_unused_keys = sorted(unused_keys)
        print(f"Found {len(sorted_unused_keys)} unused keys out of 256 possible (00-FF):")

        # Display in rows of 16 for better readability
        for i in range(0, len(sorted_unused_keys), 16):
            row_keys = sorted_unused_keys[i:i+16]
            print(" ".join(f"{key:>2}" for key in row_keys))

        return sorted_unused_keys
    else:
        print("All 256 keys (00-FF) are currently in use!")
        return []


def get_repeater(prefix, days=7, data_dir=None):
    """Get all repeater info by prefix - handles multiple repeaters with same prefix"""
    devices = extract_device_types(device_types=['repeaters'], days=days, data_dir=data_dir)

    if devices is None:
        return None

    repeaters = devices['repeaters']

    # Find all repeaters with the specified prefix
    matching_repeaters = []
    for contact in repeaters:
        contact_prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
        if contact_prefix.upper() == prefix.upper():
            matching_repeaters.append(contact)

    if not matching_repeaters:
        print(f"No repeaters found with prefix '{prefix.upper()}'")
        return None

    # Display all matching repeaters
    print(f"Found {len(matching_repeaters)} repeater(s) with prefix '{prefix.upper()}':")
    print()

    for i, contact in enumerate(matching_repeaters, 1):
        name = contact.get('name', 'Unknown')
        last_seen = contact.get('last_seen', 'Unknown')
        location = contact.get('location', {'latitude': 0, 'longitude': 0})
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

        print(f"Repeater #{i}:")
        print(f"- Name: {name}")
        print(f"- Last Seen: {formatted_last_seen}")
        print(f"- Location: {lat}, {lon}")
        print()

    # Return the list of matching repeaters
    return matching_repeaters


def get_first_repeater(prefix, days=7, data_dir=None):
    """Get the first repeater info by prefix (for backward compatibility)"""
    repeaters = get_repeater(prefix, days, data_dir=data_dir)
    if repeaters and len(repeaters) > 0:
        return repeaters[0]
    return None
