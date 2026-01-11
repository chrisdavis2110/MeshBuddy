#!/usr/bin/python3

import os
import json
import shutil
import logging
import argparse
import requests
from datetime import datetime, timezone
from helpers import load_config, get_data_dir, save_data_to_json, load_data_from_json, compare_data

config = load_config()
logger = logging.getLogger(__name__)

# Try to import cloudscraper for Cloudflare bypass, fallback to requests if not available
try:
    import cloudscraper
    USE_CLOUDSCRAPER = True
except ImportError:
    USE_CLOUDSCRAPER = False
    logger.warning("cloudscraper not installed. Install it with: pip install cloudscraper")


def get_data_from_mqtt(mqtt_api_url):
    """
    Fetch data from MQTT API endpoint

    Args:
        mqtt_api_url (str): URL of the MQTT API endpoint

    Returns:
        dict: JSON data from the API, or None if failed
    """
    try:
        # Use cloudscraper if available to bypass Cloudflare protection
        if USE_CLOUDSCRAPER:
            session = cloudscraper.create_scraper()
            logger.info("Using cloudscraper to bypass Cloudflare protection")
        else:
            session = requests.Session()
            logger.warning("Using standard requests (cloudscraper not available)")

        # Prepare headers to mimic a real browser
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://api.letsmesh.net/",
            "Origin": "https://api.letsmesh.net",
        }

        session.headers.update(headers)

        # Make the request
        response = session.get(mqtt_api_url, timeout=60, allow_redirects=True)
        response.raise_for_status()

        # Check if response is HTML (Cloudflare challenge page)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' in content_type or response.text.strip().startswith('<!DOCTYPE'):
            logger.error("API returned HTML instead of JSON - likely Cloudflare challenge page")
            logger.error(f"Response preview: {response.text[:200]}")
            if not USE_CLOUDSCRAPER:
                logger.error("Consider installing cloudscraper: pip install cloudscraper")
            return None

        data = response.json()
        return data
    except requests.RequestException as e:
        logger.error(f"Error fetching data from MQTT API: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}")
            # Try to decode response, handle encoding issues
            try:
                response_text = e.response.text[:500]
                logger.error(f"Response body: {response_text}")
            except UnicodeDecodeError:
                # Response might be binary/compressed
                logger.error(f"Response body (raw bytes, first 200): {e.response.content[:200]}")
                logger.error("Response appears to be binary or improperly encoded")
        return None
    except ValueError as e:
        # JSON decode error
        logger.error(f"Error parsing JSON response: {str(e)}")
        logger.error(f"Response preview: {response.text[:200] if 'response' in locals() else 'N/A'}")
        return None

def get_last_update_timestamp(data_dir):
    """
    Get the last update timestamp from file

    Args:
        data_dir (str): Directory where timestamp file is stored

    Returns:
        str: ISO format timestamp string, or None if file doesn't exist
    """
    timestamp_file = os.path.join(data_dir, "last_update_timestamp.json")
    if os.path.exists(timestamp_file):
        try:
            with open(timestamp_file, 'r') as f:
                data = json.load(f)
                return data.get("last_timestamp")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error reading timestamp file: {str(e)}")
            return None
    return None

def save_last_update_timestamp(data_dir):
    """
    Save the current timestamp as the last update timestamp.

    Args:
        data_dir (str): Directory where timestamp file should be stored

    Returns:
        bool: True if successful, False otherwise
    """
    timestamp_file = os.path.join(data_dir, "last_update_timestamp.json")
    try:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(timestamp_file, 'w') as f:
            json.dump({"last_timestamp": timestamp}, f, indent=2)
        return True
    except IOError as e:
        logger.error(f"Error saving timestamp file: {str(e)}")
        return False

def merge_nodes_by_key(existing_nodes, new_nodes):
    """
    Merge new nodes into existing nodes by public_key.
    Updates existing nodes if they have the same public_key, adds new ones.

    Args:
        existing_nodes (list): List of existing node dictionaries
        new_nodes (list): List of new node dictionaries to merge

    Returns:
        list: Merged list of nodes
    """
    # Create a dictionary keyed by public_key (uppercase) for fast lookup
    nodes_dict = {}
    for node in existing_nodes:
        if isinstance(node, dict):
            public_key = node.get('public_key', '')
            if public_key:
                nodes_dict[public_key.upper()] = node

    # Update or add new nodes
    for node in new_nodes:
        if isinstance(node, dict):
            public_key = node.get('public_key', '')
            if public_key:
                # Update existing or add new
                nodes_dict[public_key.upper()] = node

    # Convert back to list and sort by public_key
    merged_nodes = list(nodes_dict.values())
    merged_nodes.sort(key=lambda x: x.get('public_key', '') if isinstance(x, dict) else str(x))

    return merged_nodes

def update_nodes_data(summary_file="update_summary.txt", data_dir=None, initial=False):
        """Complete workflow: fetch data from API for each category section, save as new_nodes.json,
        compare with existing nodes.json, save comparison to updated.json, and merge/append nodes.json with new_nodes.json

        Args:
            summary_file (str): Path to save the update summary file. Defaults to "update_summary.txt"
            data_dir (str): Directory where data files are stored
            initial (bool): If True, perform initial load (no updated_since parameter). If False, use updated_since and merge.
        """
        data_dir = get_data_dir(data_dir)
        mode = "INITIAL" if initial else "INCREMENTAL"
        print(f"Starting node data update workflow ({mode} mode)...")

        # Get last update timestamp (only for incremental updates)
        last_timestamp = None
        if not initial:
            last_timestamp = get_last_update_timestamp(data_dir)
            if last_timestamp:
                print(f"Last update timestamp: {last_timestamp}")
            else:
                print("No previous timestamp found - this appears to be the first run")
        else:
            print("Initial mode: fetching all nodes (no updated_since parameter)")

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
        success_count = 0
        for category_id, section in category_sections:
            print(f"=== Processing category {category_id} ({section}) ===")

            # Get IATA codes and nodes_file for this category
            iata = config.get(section, "iata")
            nodes_file = config.get(section, "nodes_file")

            # Build the full API URL
            api_url = url_base + iata
             # Add updated_since parameter only for incremental updates (not initial)
            if not initial and last_timestamp:
                # Check if URL already has query parameters
                separator = "&" if "?" in api_url else "?"
                api_url = api_url + separator + f"updated_since={last_timestamp}"
            print(f"API URL: {api_url}")

            # Step 1: Get new data from API
            print(f"1. Fetching data from API for {iata}...")
            new_data = get_data_from_mqtt(api_url)
            if new_data is None:
                print(f"Failed to get data from API for category {category_id}")
                continue

            # Extract the actual data array if it's wrapped
            # Handle different API response formats:
            # Format 1: {"data": {"nodes": [...]}} -> extract nodes array
            # Format 2: {"data": [...]} -> extract data array
            # Format 3: Already a list -> use as is
            # Format 4: {"nodes": [...]} -> extract nodes array
            original_data = new_data
            original_type = type(new_data).__name__

            if isinstance(new_data, list):
                # Already a list, use as is
                print(f"Data is already a list with {len(new_data)} items")
                pass
            elif isinstance(new_data, dict):
                print(f"Data is a dict with keys: {list(new_data.keys())}")
                if "data" in new_data:
                    if isinstance(new_data["data"], dict) and "nodes" in new_data["data"]:
                        # Nested format: data.nodes
                        print("Extracting from nested format: data.nodes")
                        new_data = new_data["data"]["nodes"]
                    elif isinstance(new_data["data"], list):
                        # Flat format: data is already an array
                        print("Extracting from flat format: data")
                        new_data = new_data["data"]
                    else:
                        logger.error(f"Unexpected 'data' value type: {type(new_data['data'])}")
                        logger.error(f"Data keys: {list(new_data.keys())}")
                        if isinstance(new_data["data"], dict):
                            logger.error(f"Data dict keys: {list(new_data['data'].keys())}")
                        continue
                elif "nodes" in new_data:
                    # Direct nodes key
                    print("Extracting from direct nodes key")
                    new_data = new_data["nodes"]
                else:
                    logger.error(f"Unexpected dict structure. Keys: {list(new_data.keys())}")
                    logger.error(f"Sample of data structure: {str(new_data)[:500]}")
                    continue
            else:
                logger.error(f"Unexpected data format. Expected list or dict, got {type(new_data)}")
                logger.error(f"Data type: {type(new_data)}, Value preview: {str(new_data)[:200]}")
                continue

            # Ensure we have a list/array format
            if not isinstance(new_data, list):
                logger.error(f"After extraction, expected list but got {type(new_data)}")
                logger.error(f"Original data type: {type(original_data)}")
                logger.error(f"Original data keys (if dict): {list(original_data.keys()) if isinstance(original_data, dict) else 'N/A'}")
                continue

            # Step 2: Load existing nodes file
            print(f"2. Loading existing {nodes_file}...")
            old_data = load_data_from_json(nodes_file, data_dir)
            existing_nodes = old_data.get("data", []) if old_data else []

            # Step 3: Merge or replace nodes based on mode
            if initial:
                # Initial mode: replace all nodes with new data
                print(f"3. Initial mode: saving all {len(new_data)} nodes to {nodes_file}...")
                merged_nodes = new_data
            else:
                # Incremental mode: merge new nodes with existing by public_key
                print(f"3. Incremental mode: merging {len(new_data)} new nodes with {len(existing_nodes)} existing nodes...")
                merged_nodes = merge_nodes_by_key(existing_nodes, new_data)
                print(f"   Merged result: {len(merged_nodes)} total nodes")

            # Step 4: Compare the data for reporting
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

            # Step 6: Save merged nodes to nodes file
            nodes_path = os.path.join(data_dir, nodes_file)
            print(f"6. Saving merged nodes to {nodes_path}...")
            try:
                # Use save_data_to_json which wraps in timestamp structure
                if not save_data_to_json(merged_nodes, nodes_file, data_dir):
                    print(f"Failed to save merged nodes for category {category_id}")
                    continue
                print(f"Successfully saved {len(merged_nodes)} nodes to {nodes_path}")
            except Exception as e:
                logger.error(f"Error saving nodes to {nodes_path}: {str(e)}")
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
            success_count += 1

        # Save timestamp after successful runs
        if success_count > 0:
            if save_last_update_timestamp(data_dir):
                print(f"Saved update timestamp for next run")
            else:
                logger.warning("Failed to save update timestamp")

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
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Update node data from MQTT API')
    parser.add_argument('--initial', action='store_true',
                        help='Perform initial load (fetch all nodes, no updated_since parameter)')
    args = parser.parse_args()

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Run the update
    update_nodes_data(data_dir=script_dir, initial=args.initial)