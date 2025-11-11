#!/usr/bin/python3

import os
import json
import shutil
import logging
import requests
from datetime import datetime
from helpers import load_config, get_data_dir, save_data_to_json, load_data_from_json, compare_data

config = load_config()

logger = logging.getLogger(__name__)


def get_data_from_mqtt(mqtt_api_url):
    """
    Fetch data from MQTT API endpoint

    Args:
        mqtt_api_url (str): URL of the MQTT API endpoint

    Returns:
        dict: JSON data from the API, or None if failed
    """
    try:
        response = requests.get(mqtt_api_url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        logger.error(f"Error fetching data from MQTT API: {str(e)}")
        return None

def update_nodes_data(summary_file="update_summary.txt", data_dir=None):
        """Complete workflow: fetch MQTT data, save as new_nodes.json, compare with nodes.json,
        save comparison to updated.json, and replace nodes.json with new_nodes.json

        Args:
            summary_file (str): Path to save the update summary file. Defaults to "update_summary.txt"
        """
        data_dir = get_data_dir(data_dir)
        print("Starting node data update workflow...")

        # Step 1: Get new data from MQTT
        print("1. Fetching data from MQTT...")
        new_data = get_data_from_mqtt(config.get("meshcore", "mqtt_api"))
        if new_data is None:
            print("Failed to get data from MQTT")
            return False

        # Step 2: Save new data as new_nodes.json
        new_nodes_path = os.path.join(data_dir, "new_nodes.json")
        print(f"2. Saving new data to {new_nodes_path}...")
        if not save_data_to_json(new_data, "new_nodes.json"):
            print("Failed to save new data")
            return False

        # Step 3: Load existing nodes.json for comparison
        nodes_path = os.path.join(data_dir, "nodes.json")
        print(f"3. Loading existing {nodes_path} for comparison...")
        old_data = load_data_from_json("nodes.json")

        # Step 4: Compare the data
        print("4. Comparing new data with existing data...")
        comparison_result = compare_data(new_data, old_data)

        # Step 5: Save comparison results to updated.json
        updated_path = os.path.join(data_dir, "updated.json")
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
                # Display only first 2 characters for readability
                prefix = key[:2] if len(key) >= 2 else key
                line = f"- {prefix}"
                print(line)
                summary_lines.append(line)

        summary_lines.append("")
        summary_lines.append("Update workflow completed successfully!")

        # Save summary to file
        try:
            summary_path = os.path.join(data_dir, summary_file)
            with open(summary_path, 'w') as f:
                f.write('\n'.join(summary_lines))
            print(f"\nUpdate summary saved to {summary_path}")
        except Exception as e:
            logger.error(f"Error saving update summary to {summary_path}: {str(e)}")

        print("\nUpdate workflow completed successfully!")
        return True

if __name__ == "__main__":
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Run the update
    update_nodes_data(data_dir=script_dir)