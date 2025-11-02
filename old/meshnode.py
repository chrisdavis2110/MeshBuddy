#!/usr/bin/python

import asyncio
import json
import logging
import configparser
import sys
import os
import shutil
from datetime import datetime

from meshcore import MeshCore, EventType
from helpers import save_data_to_json, load_data_from_json, compare_data, load_config

# Initialize logging (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class MeshNodeBridge():
    def __init__(self, config_file="config.ini"):
        self.config = load_config(config_file)

    async def on_connected(event):
        print(f"Connected: {event.payload}")
        if event.payload.get('reconnected'):
            print("Successfully reconnected!")

    async def on_disconnected(event):
        print(f"Disconnected: {event.payload['reason']}")
        if event.payload.get('max_attempts_exceeded'):
            print("Max reconnection attempts exceeded")

    async def get_data_from_meshcore(self):
        # meshcore = await MeshCore.create_serial(self.config.get("meshcore", "usbport"), debug=True)
        # meshcore = await MeshCore.create_ble(self.config.get("meshcore", "ble"), pin=self.config.get("meshcore", "pin"), debug=True)
        meshcore = await MeshCore.create_tcp(self.config.get("meshcore", "address"), self.config.get("meshcore", "port"), debug=True)

        result = await meshcore.commands.get_contacts()
        if result.type == EventType.ERROR:
            print(f"Error getting contacts: {result.payload}")
            return None

        contacts = result.payload
        print(f"Found {len(contacts)} contacts")

        # Sort contacts by contact_id
        sorted_contacts = dict(sorted(contacts.items()))

        # Convert contacts to JSON-serializable format
        contacts_list = []
        for contact_id, contact in sorted_contacts.items():
            # Determine mode based on contact type
            contact_type = contact.get('type', 1)
            mode_map = {1: 'Companion', 2: 'Repeater', 3: 'Room Server'}
            mode = mode_map.get(contact_type, 'Companion')

            # Create a JSON-serializable contact object
            contact_data = {
                'public_key': contact_id,
                'name': contact.get('adv_name', 'Unknown'),
                'device_role': contact.get('type', 1),
                'last_seen': contact.get('last_advert', ''),
                'decoded_payload': {
                    'lat': contact.get('adv_lat', '0.0'),
                    'lon': contact.get('adv_lon', '0.0'),
                    'mode': mode,
                    'name': contact.get('adv_name', 'Unknown'),
                    'timestamp': contact.get('last_advert', ''),
                    'public_key': contact_id
                },
                'location': {
                  'latitude': contact.get('adv_lat', '0.0'),
                  'longitude': contact.get('adv_lon', '0.0')
                }
            }
            contacts_list.append(contact_data)

        await meshcore.disconnect()
        return contacts_list

    def save_data_to_json(self, data, filename="nodes.json"):
        """Save data to JSON file with timestamp"""
        return save_data_to_json(data, filename)

    def load_data_from_json(self, filename="nodes.json"):
        """Load data from JSON file"""
        return load_data_from_json(filename)

    def compare_data(self, new_data, old_data=None):
        """Compare new data with old data to find changes"""
        return compare_data(new_data, old_data)

    async def update_nodes_data(self):
        """Complete workflow: fetch Meshcore data, save as new_nodes.json, compare with nodes.json,
        save comparison to updated.json, and replace nodes.json with new_nodes.json"""

        print("Starting node data update workflow...")

        # Step 1: Get new data from Meshcore
        print("1. Fetching data from Meshcore...")
        new_data = await self.get_data_from_meshcore()
        if new_data is None:
            print("Failed to get data from Meshcore")
            return False

        # Step 2: Save new data as new_nodes.json
        print("2. Saving new data to new_nodes.json...")
        if not self.save_data_to_json(new_data, "new_nodes.json"):
            print("Failed to save new data")
            return False

        # Step 3: Load existing nodes.json for comparison
        print("3. Loading existing nodes.json for comparison...")
        old_data = self.load_data_from_json("nodes.json")

        # Step 4: Compare the data
        print("4. Comparing new data with existing data...")
        comparison_result = self.compare_data(new_data, old_data)

        # Step 5: Save comparison results to updated.json
        print("5. Saving comparison results to updated.json...")
        try:
            comparison_with_timestamp = {
                "timestamp": datetime.now().isoformat(),
                "comparison": comparison_result
            }

            with open("updated.json", 'w') as f:
                json.dump(comparison_with_timestamp, f, indent=2)

            print("Comparison results saved to updated.json")
        except Exception as e:
            logger.error(f"Error saving comparison results: {str(e)}")
            return False

        # Step 6: Replace nodes.json with new_nodes.json
        print("6. Replacing nodes.json with new_nodes.json...")
        try:
            shutil.move("new_nodes.json", "nodes.json")
            print("Successfully replaced nodes.json with new data")
        except Exception as e:
            logger.error(f"Error replacing nodes.json: {str(e)}")
            return False

        # Step 7: Print summary
        print("\n=== UPDATE SUMMARY ===")
        if comparison_result.get('new_contacts'):
            print(f"New contacts ({len(comparison_result.get('new_contacts', []))}):")
            for contact in comparison_result['new_contacts']:
                prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
                name = contact.get('name', 'Unknown')
                print(f"- {prefix}: {name}")

        if comparison_result.get('duplicate_keys'):
            print(f"Duplicate keys ({len(comparison_result.get('duplicate_keys', []))}):")
            for key in comparison_result['duplicate_keys']:
                print(f"- {key}")

        if comparison_result.get('removed_contacts'):
            print(f"Removed contacts ({len(comparison_result.get('removed_contacts', []))}):")
            for key in comparison_result['removed_contacts']:
                print(f"- {key}")

        print("\nUpdate workflow completed successfully!")
        return True

    async def run(self):
        """Main async method to run the bridge"""
        await self.update_nodes_data()


if __name__ == "__main__":
    bridge = MeshNodeBridge()
    asyncio.run(bridge.get_data_from_meshcore())