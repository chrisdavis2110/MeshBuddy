"""
Data utilities for JSON file operations and data management.
"""

import json
import os
import logging
from datetime import datetime
from .config_utils import load_config

config = load_config()

logger = logging.getLogger(__name__)


def get_data_dir(data_dir=None):
    if data_dir:
        data_dir = os.path.abspath(data_dir)
    else:
        data_dir = os.path.abspath(os.getcwd())

    # Ensure data directory exists
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def save_data_to_json(data, filename="nodes.json", data_dir=None):
    """Save data to JSON file with timestamp"""
    data_dir = get_data_dir(data_dir)
    try:
        # Sort data by public_key before saving
        if isinstance(data, list):
            sorted_data = sorted(data, key=lambda x: x.get('public_key', '') if isinstance(x, dict) else str(x))
        else:
            sorted_data = data

        # Add timestamp to the data
        data_with_timestamp = {
            "timestamp": datetime.now().isoformat(),
            "data": sorted_data
        }

        # Determine file path
        if data_dir:
            filepath = os.path.join(data_dir, filename)
        else:
            filepath = filename

        with open(filepath, 'w') as f:
            json.dump(data_with_timestamp, f, indent=2)

        print(f"Data saved to {filepath} (sorted by public_key)")
        return True
    except Exception as e:
        logger.error(f"Error saving data to JSON: {str(e)}")
        return False


def load_data_from_json(filename="nodes.json", data_dir=None):
    """Load data from JSON file"""
    data_dir = get_data_dir(data_dir)
    try:
        # Determine file path
        if data_dir:
            filepath = os.path.join(data_dir, filename)
        else:
            filepath = filename

        if not os.path.exists(filepath):
            print(f"No existing data file found: {filepath}")
            return None

        with open(filepath, 'r') as f:
            loaded_data = json.load(f)

        return loaded_data
    except Exception as e:
        logger.error(f"Error loading data from JSON: {str(e)}")
        return None


def compare_data(new_data, old_data=None):
    """Compare new data with old data to find changes"""
    if old_data is None:
        print("No previous data to compare with")
        return {
            "new_contacts": new_data,
            "duplicates": []
        }

    old_contacts = old_data.get("data", [])
    new_contacts = new_data

    # Create dictionaries to store key-name pairs for comparison
    old_key_name_pairs = {}
    new_key_name_pairs = {}

    # Extract key-name pairs from old data
    for contact in old_contacts:
        if isinstance(contact, dict):
            key = contact.get('public_key', '').upper() if contact.get('public_key') else ''
            name = contact.get('name', '')
            if key:
                old_key_name_pairs[key] = name

    # Extract key-name pairs from new data
    for contact in new_contacts:
        if isinstance(contact, dict):
            key = contact.get('public_key', '').upper() if contact.get('public_key') else ''
            name = contact.get('name', '')
            if key:
                new_key_name_pairs[key] = name

    # Find differences
    old_keys = set(old_key_name_pairs.keys())
    new_keys = set(new_key_name_pairs.keys())

    newly_added_keys = new_keys - old_keys

    # Find ALL duplicate keys (keys that appear multiple times, regardless of name) - REPEATERS ONLY
    # Count occurrences of each key in new data (repeaters only)
    key_count = {}
    for contact in new_contacts:
        if isinstance(contact, dict) and contact.get('device_role') == 2:
            key = contact.get('public_key', '').upper() if contact.get('public_key') else ''
            if key:
                key_count[key] = key_count.get(key, 0) + 1

    # Find keys that appear more than once (repeaters only)
    duplicate_keys = []
    for key, count in key_count.items():
        if count > 1:
            # Add all repeater contacts with this duplicate key
            for contact in new_contacts:
                if isinstance(contact, dict) and contact.get('device_role') == 2:
                    contact_key = contact.get('public_key', '').upper() if contact.get('public_key') else ''
                    if contact_key == key:
                        name = contact.get('name', 'Unknown')
                        # Store tuple of (prefix for display, name)
                        duplicate_keys.append((key[:2], name))

    # Sort duplicate keys by key prefix
    duplicate_keys.sort(key=lambda x: x[0])

    # Get actual contact objects for newly added
    new_contacts_list = []
    for contact in new_contacts:
        if isinstance(contact, dict):
            key = contact.get('public_key', '')[:2].upper() if contact.get('public_key') else ''
            if key and key in newly_added_keys:
                new_contacts_list.append(contact)
        else:
            if str(contact) in newly_added_keys:
                new_contacts_list.append(contact)

    # Get actual contact objects for duplicates (repeaters only)
    duplicate_contacts = []
    duplicate_key_prefixes = [key for key, name in duplicate_keys]  # Extract just the prefixes
    for contact in new_contacts:
        if isinstance(contact, dict) and contact.get('device_role') == 2:
            key = contact.get('public_key', '')[:2]
            if key in duplicate_key_prefixes:  # Include only repeaters
                duplicate_contacts.append(contact)
        else:
            if str(contact) in duplicate_key_prefixes:
                duplicate_contacts.append(contact)

    return {
        "new_contacts": new_contacts_list,
        "duplicates": duplicate_contacts,
        "new_keys": list(newly_added_keys),
        "duplicate_keys": duplicate_keys
    }
