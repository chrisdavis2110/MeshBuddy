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
        """Complete workflow: fetch data from API for each category section, save as new_nodes.json,
        compare with existing nodes.json, save comparison to updated.json, and replace nodes.json with new_nodes.json

        Args:
            summary_file (str): Path to save the update summary file. Defaults to "update_summary.txt"
        """
        data_dir = get_data_dir(data_dir)
        print("Starting node data update workflow...")

        # Get url_base from [api] section
        try:
            url_base = config.get("api", "url_base")
        except Exception as e:
            logger.error(f"Error getting url_base from [api] section: {str(e)}")
            print("Failed to get url_base from config")
            return False

        # Get all category sections (numeric section names with iata and nodes_file)
        all_sections = config.sections()
        category_sections = []
        for section in all_sections:
            try:
                # Try to convert to int to see if it's a category ID
                category_id = int(section)
                # Check if it has the required keys
                if config.has_option(section, "iata") and config.has_option(section, "nodes_file"):
                    category_sections.append((category_id, section))
            except (ValueError, TypeError):
                # Not a numeric section, skip it
                continue

        if not category_sections:
            print("No category sections found with iata and nodes_file")
            return False

        print(f"Found {len(category_sections)} category section(s) to update")

        # Process each category section
        all_summaries = []
        for category_id, section in category_sections:
            print(f"=== Processing category {category_id} ({section}) ===")

            # Get IATA codes and nodes_file for this category
            iata = config.get(section, "iata")
            nodes_file = config.get(section, "nodes_file")

            # Build the full API URL
            api_url = url_base + iata
            print(f"API URL: {api_url}")

            # Step 1: Get new data from API
            print(f"1. Fetching data from API for {iata}...")
            new_data = get_data_from_mqtt(api_url)
            if new_data is None:
                print(f"Failed to get data from API for category {category_id}")
                continue

            # Extract the actual data array if it's wrapped
            if isinstance(new_data, dict) and "data" in new_data:
                new_data = new_data["data"]

            # Step 2: Save new data as new_nodes.json (temporary file)
            temp_nodes_file = f"new_{nodes_file}"
            print(f"2. Saving new data to {temp_nodes_file}...")
            if not save_data_to_json(new_data, temp_nodes_file, data_dir):
                print(f"Failed to save new data for category {category_id}")
                continue

            # Step 3: Load existing nodes file for comparison
            print(f"3. Loading existing {nodes_file} for comparison...")
            old_data = load_data_from_json(nodes_file, data_dir)

            # Step 4: Compare the data
            print("4. Comparing new data with existing data...")
            comparison_result = compare_data(new_data, old_data)

            # Step 5: Save comparison results to updated.json (category-specific)
            updated_file = f"updated_{nodes_file.replace('.json', '')}.json"
            updated_path = os.path.join(data_dir, updated_file)
            print(f"5. Saving comparison results to {updated_path}...")
            try:
                comparison_with_timestamp = {
                    "timestamp": datetime.now().isoformat(),
                    "category_id": category_id,
                    "iata": iata,
                    "comparison": comparison_result
                }

                with open(updated_path, 'w') as f:
                    json.dump(comparison_with_timestamp, f, indent=2)

                print(f"Comparison results saved to {updated_path}")
            except Exception as e:
                logger.error(f"Error saving comparison results: {str(e)}")
                continue

            # Step 6: Replace nodes file with new data
            nodes_path = os.path.join(data_dir, nodes_file)
            temp_nodes_path = os.path.join(data_dir, temp_nodes_file)
            print(f"6. Replacing {nodes_path} with {temp_nodes_path}...")
            try:
                shutil.move(temp_nodes_path, nodes_path)
                print(f"Successfully replaced {nodes_path} with new data")
            except Exception as e:
                logger.error(f"Error replacing {nodes_path}: {str(e)}")
                continue

            # # Step 7: Build summary for this category
            # category_summary = []
            # category_summary.append(f"\n=== UPDATE SUMMARY - Category {category_id} ({iata}) ===")
            # category_summary.append(f"Nodes file: {nodes_file}")
            # category_summary.append(f"Timestamp: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
            # category_summary.append("")

            # if comparison_result.get('new_contacts'):
            #     category_summary.append(f"New contacts ({len(comparison_result.get('new_contacts', []))}):")
            #     for contact in comparison_result['new_contacts']:
            #         prefix = contact.get('public_key', '')[:2] if contact.get('public_key') else '??'
            #         name = contact.get('name', 'Unknown')
            #         line = f"- {prefix}: {name}"
            #         category_summary.append(line)

            # if comparison_result.get('duplicate_keys'):
            #     category_summary.append(f"Duplicate keys ({len(comparison_result.get('duplicate_keys', []))}):")
            #     for key, name in comparison_result['duplicate_keys']:
            #         line = f"- {key}: {name}"
            #         category_summary.append(line)

            # if comparison_result.get('removed_contacts'):
            #     category_summary.append(f"Removed contacts ({len(comparison_result.get('removed_contacts', []))}):")
            #     for key in comparison_result['removed_contacts']:
            #         # Display only first 2 characters for readability
            #         prefix = key[:2] if len(key) >= 2 else key
            #         line = f"- {prefix}"
            #         category_summary.append(line)

            # category_summary.append("")
            # category_summary.append(f"Update completed successfully for category {category_id}!")
            # all_summaries.extend(category_summary)

            # Print summary for this category
            # print("\n" + "\n".join(category_summary))
            print(f"Update completed successfully for category {category_id}!\n")

        # Save combined summary to file
        # try:
        #     summary_path = os.path.join(data_dir, summary_file)
        #     summary_lines = []
        #     summary_lines.append("=== UPDATE SUMMARY - ALL CATEGORIES ===")
        #     summary_lines.append(f"Timestamp: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
        #     summary_lines.append(f"Categories processed: {len(category_sections)}")
        #     summary_lines.append("")
        #     summary_lines.extend(all_summaries)
        #     summary_lines.append("")
        #     summary_lines.append("Update workflow completed successfully!")

        #     with open(summary_path, 'w') as f:
        #         f.write('\n'.join(summary_lines))
        #     print(f"\nCombined update summary saved to {summary_path}")
        # except Exception as e:
        #     logger.error(f"Error saving update summary to {summary_path}: {str(e)}")

        print("\nUpdate workflow completed successfully!")
        return True

if __name__ == "__main__":
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Run the update
    update_nodes_data(data_dir=script_dir)