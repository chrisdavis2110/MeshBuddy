#!/usr/bin/python

import json
import logging
import configparser
import sys
import requests
import os
import shutil
from datetime import datetime

# Initialize logging (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class MeshMQTTBridge():
    def __init__(self, config_file="config.ini", data_dir=None):
        self.config = configparser.ConfigParser()
        try:
            self.config.read(config_file)
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            sys.exit(1)

        # Set data directory - use absolute path if provided, otherwise current directory
        if data_dir:
            self.data_dir = os.path.abspath(data_dir)
        else:
            self.data_dir = os.path.abspath(os.getcwd())

        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)

    def get_data_from_mqtt(self):
        mqtt_api_url = self.config.get("meshcore", "mqtt_api")
        try:
            response = requests.get(mqtt_api_url)
            response.raise_for_status()
            data = response.json()
            return data
        except requests.RequestException as e:
            logger.error(f"Error fetching data from MQTT API: {str(e)}")
            return None

    def save_data_to_json(self, data, filename="nodes.json"):
        """Save data to JSON file with timestamp"""
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

            filepath = os.path.join(self.data_dir, filename)
            with open(filepath, 'w') as f:
                json.dump(data_with_timestamp, f, indent=2)

            print(f"Data saved to {filepath} (sorted by public_key)")
            return True
        except Exception as e:
            logger.error(f"Error saving data to JSON: {str(e)}")
            return False

    def load_data_from_json(self, filename="nodes.json"):
        """Load data from JSON file"""
        try:
            filepath = os.path.join(self.data_dir, filename)
            if not os.path.exists(filepath):
                print(f"No existing data file found: {filepath}")
                return None

            with open(filepath, 'r') as f:
                loaded_data = json.load(f)

            print(f"Data loaded from {filepath}")
            return loaded_data
        except Exception as e:
            logger.error(f"Error loading data from JSON: {str(e)}")
            return None

    def compare_data(self, new_data, old_data=None):
        """Compare new data with old data to find changes"""
        if old_data is None:
            print("No previous data to compare with")
            return {
                "new_contacts": new_data,
                "duplicates": [],
                "removed_contacts": []
            }

        old_contacts = old_data.get("data", [])
        new_contacts = new_data

        # Create dictionaries to store key-name pairs for comparison
        old_key_name_pairs = {}
        new_key_name_pairs = {}

        # Extract key-name pairs from old data
        for contact in old_contacts:
            if isinstance(contact, dict):
                key = contact.get('public_key', '')[:2]
                name = contact.get('name', '')
                old_key_name_pairs[key] = name

        # Extract key-name pairs from new data
        for contact in new_contacts:
            if isinstance(contact, dict):
                key = contact.get('public_key', '')[:2]
                name = contact.get('name', '')
                new_key_name_pairs[key] = name

        # Find differences
        old_keys = set(old_key_name_pairs.keys())
        new_keys = set(new_key_name_pairs.keys())

        newly_added_keys = new_keys - old_keys
        removed_keys = old_keys - new_keys

        # Find ALL duplicate keys (keys that appear multiple times, regardless of name) - REPEATERS ONLY
        # Count occurrences of each key in new data (repeaters only)
        key_count = {}
        for contact in new_contacts:
            if isinstance(contact, dict) and contact.get('device_role') == 2:
                key = contact.get('public_key', '')[:2]
                if key:
                    key_count[key] = key_count.get(key, 0) + 1

        # Find keys that appear more than once (repeaters only)
        duplicate_keys = []
        for key, count in key_count.items():
            if count > 1:
                # Add all repeater contacts with this duplicate key
                for contact in new_contacts:
                    if isinstance(contact, dict) and contact.get('device_role') == 2:
                        contact_key = contact.get('public_key', '')[:2]
                        if contact_key == key:
                            name = contact.get('name', 'Unknown')
                            duplicate_keys.append((key, name))  # Store tuple of (prefix, name)

        # Sort duplicate keys by key prefix
        duplicate_keys.sort(key=lambda x: x[0])

        # Get actual contact objects for newly added
        new_contacts_list = []
        for contact in new_contacts:
            if isinstance(contact, dict):
                key = contact.get('public_key', '')[:2]
                if key in newly_added_keys:
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
            "removed_contacts": list(removed_keys),
            "new_keys": list(newly_added_keys),
            "duplicate_keys": duplicate_keys
        }

    def update_nodes_data(self, summary_file="update_summary.txt"):
        """Complete workflow: fetch MQTT data, save as new_nodes.json, compare with nodes.json,
        save comparison to updated.json, and replace nodes.json with new_nodes.json

        Args:
            summary_file (str): Path to save the update summary file. Defaults to "update_summary.txt"
        """

        print("Starting node data update workflow...")

        # Step 1: Get new data from MQTT
        print("1. Fetching data from MQTT...")
        new_data = self.get_data_from_mqtt()
        if new_data is None:
            print("Failed to get data from MQTT")
            return False

        # Step 2: Save new data as new_nodes.json
        new_nodes_path = os.path.join(self.data_dir, "new_nodes.json")
        print(f"2. Saving new data to {new_nodes_path}...")
        if not self.save_data_to_json(new_data, "new_nodes.json"):
            print("Failed to save new data")
            return False

        # Step 3: Load existing nodes.json for comparison
        nodes_path = os.path.join(self.data_dir, "nodes.json")
        print(f"3. Loading existing {nodes_path} for comparison...")
        old_data = self.load_data_from_json("nodes.json")

        # Step 4: Compare the data
        print("4. Comparing new data with existing data...")
        comparison_result = self.compare_data(new_data, old_data)

        # Step 5: Save comparison results to updated.json
        updated_path = os.path.join(self.data_dir, "updated.json")
        print(f"5. Saving comparison results to {updated_path}...")
        try:
            comparison_with_timestamp = {
                "timestamp": datetime.now().isoformat(),
                "comparison": comparison_result
            }

            with open(updated_path, 'w') as f:
                json.dump(comparison_with_timestamp, f, indent=2)

            print(f"Comparison results saved to {updated_path}")
        except Exception as e:
            logger.error(f"Error saving comparison results: {str(e)}")
            return False

        # Step 6: Replace nodes.json with new_nodes.json
        print(f"6. Replacing {nodes_path} with {new_nodes_path}...")
        try:
            shutil.move(new_nodes_path, nodes_path)
            print(f"Successfully replaced {nodes_path} with new data")
        except Exception as e:
            logger.error(f"Error replacing {nodes_path}: {str(e)}")
            return False

        # Step 7: Print summary and save to file
        print("\n=== UPDATE SUMMARY ===")

        # Build summary content for file
        summary_lines = []
        summary_lines.append("=== UPDATE SUMMARY ===")
        summary_lines.append(f"Timestamp: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
        summary_lines.append("")

        if comparison_result.get('new_contacts'):
            print(f"New contacts ({len(comparison_result.get('new_contacts', []))}):")
            summary_lines.append(f"New contacts ({len(comparison_result.get('new_contacts', []))}):")
            for contact in comparison_result['new_contacts']:
                prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
                name = contact.get('name', 'Unknown')
                line = f"- {prefix}: {name}"
                print(line)
                summary_lines.append(line)

        if comparison_result.get('duplicate_keys'):
            print(f"Duplicate keys ({len(comparison_result.get('duplicate_keys', []))}):")
            summary_lines.append(f"Duplicate keys ({len(comparison_result.get('duplicate_keys', []))}):")
            for key, name in comparison_result['duplicate_keys']:
                line = f"- {key}: {name}"
                print(line)
                summary_lines.append(line)

        if comparison_result.get('removed_contacts'):
            print(f"Removed contacts ({len(comparison_result.get('removed_contacts', []))}):")
            summary_lines.append(f"Removed contacts ({len(comparison_result.get('removed_contacts', []))}):")
            for key in comparison_result['removed_contacts']:
                line = f"- {key}"
                print(line)
                summary_lines.append(line)

        summary_lines.append("")
        summary_lines.append("Update workflow completed successfully!")

        # Save summary to file
        try:
            summary_path = os.path.join(self.data_dir, summary_file)
            with open(summary_path, 'w') as f:
                f.write('\n'.join(summary_lines))
            print(f"\nUpdate summary saved to {summary_path}")
        except Exception as e:
            logger.error(f"Error saving update summary to {summary_path}: {str(e)}")

        print("\nUpdate workflow completed successfully!")
        return True

    def is_within_window(self, contact, min_days=0, max_days=7):
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

    def extract_device_types(self, device_types=None, days=7):
        """
        Extract specific device types from nodes data

        Args:
            device_types (list): List of device types to extract. Options:
                - 'repeaters': device_role == 2
                - 'companions': device_role == 1
                - 'room_servers': mode == "Room Server"
                If None, extracts all three types
            days (int): Maximum days since last seen (default: 7)

        Returns:
            dict: Dictionary with device types as keys and lists of devices as values
        """
        data = self.load_data_from_json()

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
            if not self.is_within_window(contact, min_days=0, max_days=days):
                continue

            # Check device type and add to appropriate list
            if 'repeaters' in device_types and contact.get('device_role') == 2:
                result['repeaters'].append(contact)
            elif 'companions' in device_types and contact.get('device_role') == 1:
                result['companions'].append(contact)
            elif 'room_servers' in device_types and contact.get('device_role') == 3:
                result['room_servers'].append(contact)

        return result

    def get_companion_list(self, days=7):
        """Get list of companions using the new extraction function"""
        devices = self.extract_device_types(['companions'], days)

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

    def get_room_server_list(self, days=7):
        """Get list of room servers using the new extraction function"""
        devices = self.extract_device_types(['room_servers'], days)

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

    def get_repeater_list(self, days=7):
        """Get list of repeaters using the new extraction function"""
        devices = self.extract_device_types(['repeaters'], days)

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

    def get_repeater_duplicates(self):
        """Get repeater duplicates using the new extraction function"""
        devices = self.extract_device_types(['repeaters'])

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
            print(f"Found {len(duplicate_prefixes)} duplicate prefixes:")

            duplicate_list = []
            for prefix in duplicate_prefixes:
                # Get all repeaters with this prefix
                prefix_repeaters = [contact for contact in repeaters
                                  if contact.get('public_key', '')[:2] == prefix]

                print(f"\nPrefix '{prefix}' ({len(prefix_repeaters)} repeaters):")
                for contact in prefix_repeaters:
                    name = contact.get('name', 'Unknown')
                    repeater_info = f"{prefix}: {name}"
                    print(f"  - {repeater_info}")
                    duplicate_list.append(repeater_info)
        else:
            print("No duplicate prefixes found")
            duplicate_list = []

        return duplicate_list

    def get_repeater_offline(self, days=8):
        """Show repeaters that haven't been heard in 2 days"""
        # Get repeaters that are 2-8 days old
        devices = self.extract_device_types(['repeaters'], days)

        if devices is None:
            return None

        repeaters = devices['repeaters']

        # Filter to only those that are 2+ days old
        offline_data = [contact for contact in repeaters
                       if self.is_within_window(contact, min_days=2, max_days=days)]

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

    def get_unused_keys(self):
        """Show which hex keys from 00 to FF are not currently being used"""
        devices = self.extract_device_types(['repeaters'])

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

    def get_repeater(self, prefix):
        """Get repeater info by prefix"""
        data = self.load_data_from_json()

        if data is None:
            print("No data found in nodes.json")
            return

        # Extract contacts from the loaded data
        contacts = data.get("data", []) if isinstance(data, dict) else data

        if isinstance(contacts, list):
            for contact in contacts:
                if isinstance(contact, dict):
                    contact_prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
                    if contact_prefix.upper() == prefix.upper() and contact.get('device_role') == 2 and self.is_within_window(contact):
                         name = contact.get('name', 'Unknown')
                         last_seen = contact.get('last_seen', 'Unknown')
                         location = contact.get('location', {'latitude': 0, 'longitude': 0})
                         lat = location.get('latitude', 0)
                         lon = location.get('longitude', 0)

                         # Format last_seen timestamp
                         formatted_last_seen = "Unknown"
                         if last_seen != 'Unknown':
                            print(last_seen)
                            try:
                                last_seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                                print(last_seen_dt)
                                formatted_last_seen = last_seen_dt.strftime("%B %d, %Y %I:%M %p")
                            except Exception:
                                formatted_last_seen = "Invalid timestamp"

                         print(f"Repeater Info for Prefix '{prefix.upper()}':")
                         print(f"- Name: {name}")
                         print(f"- Last Seen: {formatted_last_seen}")
                         print(f"- Location: {lat}, {lon}")
                         return contact
            print(f"No repeater found with prefix '{prefix}'")
            return None
        else:
            print("No valid contact data found")
            return None