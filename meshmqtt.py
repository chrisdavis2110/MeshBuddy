#!/usr/bin/python

import json
import logging
import configparser
import sys
import requests
import os
import shutil
from datetime import datetime
from helpers import (
    save_data_to_json,
    load_data_from_json,
    compare_data,
    extract_device_types,
    is_within_window,
    get_data_from_mqtt,
    load_config
)

# Initialize logging (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class MeshMQTTBridge():
    def __init__(self, config_file="config.ini", data_dir=None):
        self.config = load_config(config_file)

        # Set data directory - use absolute path if provided, otherwise current directory
        if data_dir:
            self.data_dir = os.path.abspath(data_dir)
        else:
            self.data_dir = os.path.abspath(os.getcwd())

        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)

    def get_data_from_mqtt(self):
        mqtt_api_url = self.config.get("meshcore", "mqtt_api")
        return get_data_from_mqtt(mqtt_api_url)

    def save_data_to_json(self, data, filename="nodes.json"):
        """Save data to JSON file with timestamp"""
        return save_data_to_json(data, filename, self.data_dir)

    def load_data_from_json(self, filename="nodes.json"):
        """Load data from JSON file"""
        return load_data_from_json(filename, self.data_dir)

    def compare_data(self, new_data, old_data=None):
        """Compare new data with old data to find changes"""
        return compare_data(new_data, old_data)

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
        return extract_device_types(device_types=device_types, days=days, data_dir=self.data_dir)

    def get_companion_list(self, days=7):
        """Get list of companions using the new extraction function"""
        from helpers import get_companion_list
        return get_companion_list(days, self.data_dir)

    def get_room_server_list(self, days=7):
        """Get list of room servers using the new extraction function"""
        from helpers import get_room_server_list
        return get_room_server_list(days, self.data_dir)

    def get_repeater_list(self, days=7):
        """Get list of repeaters using the new extraction function"""
        from helpers import get_repeater_list
        return get_repeater_list(days, self.data_dir)

    def get_repeater_duplicates(self, days=7):
        """Get repeater duplicates using the new extraction function"""
        from helpers import get_repeater_duplicates
        return get_repeater_duplicates(days, self.data_dir)

    def get_repeater_offline(self, days=14):
        """Show repeaters that haven't been heard in 3 days"""
        from helpers import get_repeater_offline
        return get_repeater_offline(days, self.data_dir)

    def get_unused_keys(self, days=7):
        """Show which hex keys from 00 to FF are not currently being used"""
        from helpers import get_unused_keys
        return get_unused_keys(days, self.data_dir)

    def get_repeater(self, prefix, days=7):
        """Get all repeater info by prefix - handles multiple repeaters with same prefix"""
        from helpers import get_repeater
        return get_repeater(prefix, days, self.data_dir)

    def get_first_repeater(self, prefix, days=7):
        """Get the first repeater info by prefix (for backward compatibility)"""
        from helpers import get_first_repeater
        return get_first_repeater(prefix, days, self.data_dir)