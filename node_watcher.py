#!/usr/bin/python
"""
Node watcher that monitors nodes.json and automatically:
1. Removes reserved nodes when a repeater with the same hex prefix is detected
2. Removes nodes from removedNodes.json if they've advertised recently
3. Adds repeaters to removedNodes.json if they haven't been seen in over 14 days
"""

import json
import os
import logging
import time
from datetime import datetime
from typing import Set, Dict, Optional

from helpers.config_utils import load_config

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Configuration
CHECK_INTERVAL = 60  # Check every 60 seconds
RECENT_DAYS = 1  # Consider "recently advertised" if last_seen within 1 day
REMOVAL_THRESHOLD_DAYS = 14  # Add nodes to removedNodes if not seen in 14+ days


class NodeWatcher:
    """Watches nodes.json for changes and manages reserved/removed nodes"""

    def __init__(self, nodes_file: str, reserved_nodes_file: str, removed_nodes_file: str, owners_file: Optional[str] = None):
        self.nodes_file = nodes_file
        self.reserved_nodes_file = reserved_nodes_file
        self.removed_nodes_file = removed_nodes_file
        self.owners_file = owners_file or "repeaterOwners.json"
        self.known_node_keys: Set[str] = set()
        self.known_nodes_map: Dict[str, Dict] = {}  # Store full node data for missing node tracking
        self.last_file_mtime = 0
        self.processed_lines = 0

    def load_nodes(self) -> Optional[Dict]:
        """Load nodes.json and return the data"""
        # Retry logic to handle race conditions when file is being written
        max_retries = 3
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                if not os.path.exists(self.nodes_file):
                    logger.warning(f"{self.nodes_file} not found")
                    return None

                # Check if file is empty before trying to parse
                if os.path.getsize(self.nodes_file) == 0:
                    if attempt < max_retries - 1:
                        logger.debug(f"{self.nodes_file} is empty, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.warning(f"{self.nodes_file} is empty after {max_retries} attempts")
                        return None

                with open(self.nodes_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{self.nodes_file} appears empty, retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.warning(f"{self.nodes_file} is empty after {max_retries} attempts")
                            return None

                    # Parse JSON from content string
                    return json.loads(content)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error parsing {self.nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error parsing {self.nodes_file}: {e}")
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error loading {self.nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error loading {self.nodes_file}: {e}")
                    return None

        # Fallback (should never reach here)
        return None

    def load_reserved_nodes(self) -> Optional[Dict]:
        """Load reservedNodes.json and return the data"""
        # Retry logic to handle race conditions when file is being written
        max_retries = 3
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                if not os.path.exists(self.reserved_nodes_file):
                    logger.debug(f"{self.reserved_nodes_file} not found")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }

                # Check if file is empty before trying to parse
                if os.path.getsize(self.reserved_nodes_file) == 0:
                    if attempt < max_retries - 1:
                        logger.debug(f"{self.reserved_nodes_file} is empty, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.debug(f"{self.reserved_nodes_file} is empty after {max_retries} attempts")
                        return {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }

                with open(self.reserved_nodes_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{self.reserved_nodes_file} appears empty, retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.debug(f"{self.reserved_nodes_file} is empty after {max_retries} attempts")
                            return {
                                "timestamp": datetime.now().isoformat(),
                                "data": []
                            }

                    # Parse JSON from content string (not file handle)
                    return json.loads(content)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error parsing {self.reserved_nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error parsing {self.reserved_nodes_file}: {e}")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error loading {self.reserved_nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error loading {self.reserved_nodes_file}: {e}")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }

        # Fallback (should never reach here)
        return {
            "timestamp": datetime.now().isoformat(),
            "data": []
        }

    def save_reserved_nodes(self, data: Dict):
        """Save reservedNodes.json"""
        try:
            data["timestamp"] = datetime.now().isoformat()
            with open(self.reserved_nodes_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Updated {self.reserved_nodes_file}")
        except Exception as e:
            logger.error(f"Error saving {self.reserved_nodes_file}: {e}")

    def load_removed_nodes(self) -> Optional[Dict]:
        """Load removedNodes.json and return the data"""
        # Retry logic to handle race conditions when file is being written
        max_retries = 3
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                if not os.path.exists(self.removed_nodes_file):
                    logger.debug(f"{self.removed_nodes_file} not found")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }

                # Check if file is empty before trying to parse
                if os.path.getsize(self.removed_nodes_file) == 0:
                    if attempt < max_retries - 1:
                        logger.debug(f"{self.removed_nodes_file} is empty, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.debug(f"{self.removed_nodes_file} is empty after {max_retries} attempts")
                        return {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }

                with open(self.removed_nodes_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{self.removed_nodes_file} appears empty, retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.debug(f"{self.removed_nodes_file} is empty after {max_retries} attempts")
                            return {
                                "timestamp": datetime.now().isoformat(),
                                "data": []
                            }

                    # Parse JSON from content string (not file handle)
                    return json.loads(content)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error parsing {self.removed_nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error parsing {self.removed_nodes_file}: {e}")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error loading {self.removed_nodes_file} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error loading {self.removed_nodes_file}: {e}")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }

        # Fallback (should never reach here)
        return {
            "timestamp": datetime.now().isoformat(),
            "data": []
        }

    def save_removed_nodes(self, data: Dict):
        """Save removedNodes.json"""
        try:
            data["timestamp"] = datetime.now().isoformat()
            with open(self.removed_nodes_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Updated {self.removed_nodes_file}")
        except Exception as e:
            logger.error(f"Error saving {self.removed_nodes_file}: {e}")

    def is_node_recently_seen(self, node: Dict, days: int = RECENT_DAYS) -> bool:
        """Check if a node has been seen recently (within the last N days)"""
        try:
            last_seen_str = node.get('last_seen', '')
            if not last_seen_str:
                return False

            last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
            now = datetime.now(last_seen.tzinfo)
            days_ago = (now - last_seen).days

            return days_ago < days
        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing last_seen timestamp '{last_seen_str}': {e}")
            return False

    def _add_owner_to_repeater_owners(self, node: Dict, reserved_node: Dict):
        """Add owner information to repeaterOwners file before removing from reservedNodes"""
        try:
            username = reserved_node.get('username', 'Unknown')
            user_id = reserved_node.get('user_id', None)
            public_key = node.get('public_key', '')

            if not public_key:
                return False

            # Load or create owners file
            if os.path.exists(self.owners_file):
                try:
                    with open(self.owners_file, 'r') as f:
                        owners_data = json.load(f)
                except (json.JSONDecodeError, Exception):
                    owners_data = {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }
            else:
                owners_data = {
                    "timestamp": datetime.now().isoformat(),
                    "data": []
                }

            # Check if this public_key already exists
            existing_owner = None
            for owner in owners_data.get('data', []):
                if owner.get('public_key', '').upper() == public_key.upper():
                    existing_owner = owner
                    break

            if existing_owner:
                # Already exists, skip
                return False

            # Add new owner entry
            owner_entry = {
                "public_key": public_key,
                "name": node.get('name', 'Unknown'),
                "username": username,
                "user_id": user_id
            }

            owners_data['data'].append(owner_entry)
            owners_data['timestamp'] = datetime.now().isoformat()

            # Save to file
            with open(self.owners_file, 'w') as f:
                json.dump(owners_data, f, indent=2)

            logger.info(f"Added repeater owner: {username} (public_key: {public_key[:10]}...) to {self.owners_file}")
            return True

        except Exception as e:
            logger.error(f"Error adding owner to repeaterOwners: {e}")
            return False

    def check_new_repeaters_for_reserved(self, nodes_data: Dict):
        """Check if new repeaters match reserved nodes and remove from reserved list"""
        nodes_list = nodes_data.get('data', [])
        current_node_keys = set()
        current_nodes_map = {}

        # Extract all current node keys
        for node in nodes_list:
            public_key = node.get('public_key')
            if public_key and node.get('device_role') == 2:
                current_node_keys.add(public_key)
                current_nodes_map[public_key] = node

        # If this is the first check, initialize known_node_keys and known_nodes_map
        if not self.known_node_keys:
            self.known_node_keys = current_node_keys.copy()
            self.known_nodes_map = current_nodes_map.copy()
            logger.info(f"Initialized node watcher with {len(self.known_node_keys)} existing nodes")
            # Still check reserved nodes even on first run
        else:
            # Find keys that have disappeared (were seen before but not now)
            missing_keys = self.known_node_keys - current_node_keys
            if missing_keys:
                logger.info(f"Found {len(missing_keys)} node(s) that are no longer in {self.nodes_file}")
                # Add missing nodes to removed list
                self._add_missing_nodes_to_removed(missing_keys)

        # Load reserved nodes
        reserved_data = self.load_reserved_nodes()
        if not reserved_data:
            self.known_node_keys = current_node_keys.copy()
            return

        reserved_list = reserved_data.get('data', [])
        if not reserved_list:
            # No reserved nodes, nothing to check
            self.known_node_keys = current_node_keys.copy()
            return

        # Check all current repeaters against reserved nodes
        # Match by: public_key prefix (first 2 chars) AND node name contains reserved name (case-insensitive)
        updated_reserved_list = []
        removed_any = False

        for reserved_node in reserved_list:
            reserved_prefix = reserved_node.get('prefix', '').upper()
            reserved_name = reserved_node.get('name', '').strip()

            # Check if any current repeater matches this reserved node
            matched = False
            matched_node = None
            matched_public_key = None

            for public_key, node in current_nodes_map.items():
                node_prefix = public_key.upper()[:2] if len(public_key) >= 2 else ''
                node_name = node.get('name', '').strip()

                # Match if prefix matches and node name contains reserved name (case-insensitive)
                if (node_prefix == reserved_prefix and
                    reserved_name.lower() in node_name.lower() and
                    node.get('device_role') == 2):
                    matched_node = node
                    matched_public_key = public_key
                    matched = True
                    break

            if matched and matched_node:
                # First, transfer owner to repeaterOwners file
                self._add_owner_to_repeater_owners(matched_node, reserved_node)

                # Then remove from reserved list
                logger.info(f"Repeater with public_key {matched_public_key[:2].upper()} and name '{matched_node.get('name', '').strip()}' matches reserved entry - removing from reserved list")
                removed_any = True
            else:
                # Keep this reserved node in the list
                updated_reserved_list.append(reserved_node)

        if removed_any:
            reserved_data['data'] = updated_reserved_list
            self.save_reserved_nodes(reserved_data)

        # Update known_node_keys and known_nodes_map
        self.known_node_keys = current_node_keys.copy()
        self.known_nodes_map = current_nodes_map.copy()

    def _add_missing_nodes_to_removed(self, missing_keys: Set[str]):
        """Add nodes that are no longer in nodes.json to the removed list"""
        if not missing_keys:
            return

        # Load removed nodes
        removed_data = self.load_removed_nodes()
        if not removed_data:
            removed_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        removed_list = removed_data.get('data', [])
        removed_public_keys = {node.get('public_key', '') for node in removed_list if node.get('public_key')}

        # Get full node data from known_nodes_map for missing nodes
        nodes_to_add = []
        for missing_key in missing_keys:
            if missing_key not in removed_public_keys:
                # Get the full node data from when we last saw it
                known_node = self.known_nodes_map.get(missing_key)
                if known_node:
                    # Use the full node data
                    node_entry = known_node.copy()
                    nodes_to_add.append(node_entry)
                    removed_public_keys.add(missing_key)
                    node_name = known_node.get('name', 'Unknown')
                    logger.info(f"Node with public_key {missing_key[:8]} ({node_name}) is no longer in {self.nodes_file} - adding to removed list")
                else:
                    # Fallback if we don't have the node data
                    node_entry = {
                        "public_key": missing_key,
                        "name": "Unknown",
                    }
                    nodes_to_add.append(node_entry)
                    removed_public_keys.add(missing_key)
                    logger.info(f"Node with public_key {missing_key[:8]} is no longer in {self.nodes_file} - adding to removed list (no previous data)")

        if nodes_to_add:
            removed_list.extend(nodes_to_add)
            removed_data['data'] = removed_list
            self.save_removed_nodes(removed_data)
            logger.info(f"Added {len(nodes_to_add)} missing node(s) to {self.removed_nodes_file}")

    def check_removed_nodes_for_recent_activity(self, nodes_data: Dict):
        """Check if any removed nodes have advertised recently and remove them from removed list"""
        nodes_list = nodes_data.get('data', [])

        # Create a map of current nodes by public_key for quick lookup
        current_nodes_map = {}
        for node in nodes_list:
            public_key = node.get('public_key')
            if public_key and node.get('device_role') == 2:
                current_nodes_map[public_key] = node

        # Load removed nodes
        removed_data = self.load_removed_nodes()
        if not removed_data:
            return

        removed_list = removed_data.get('data', [])
        if not removed_list:
            return  # No removed nodes to check

        # Check each removed node
        updated_removed_list = []
        removed_any = False

        for removed_node in removed_list:
            removed_public_key = removed_node.get('public_key', '')

            # Check if this node exists in current nodes.json
            if removed_public_key in current_nodes_map:
                current_node = current_nodes_map[removed_public_key]

                # Check if it's been seen recently
                if self.is_node_recently_seen(current_node):
                    node_hex = current_node.get('public_key', '')[:2].upper() if current_node.get('public_key') else ''
                    node_name = current_node.get('name', 'Unknown')
                    logger.info(f"Removed node {node_hex}: {node_name} has advertised recently - removing from removed list")
                    removed_any = True
                    # Don't add to updated_removed_list (remove it)
                else:
                    # Node exists but hasn't been seen recently, keep it in removed list
                    updated_removed_list.append(removed_node)
            else:
                # Node doesn't exist in current nodes.json, keep it in removed list
                updated_removed_list.append(removed_node)

        if removed_any:
            removed_data['data'] = updated_removed_list
            self.save_removed_nodes(removed_data)

    def check_nodes_for_removal(self, nodes_data: Dict):
        """Check if repeaters haven't been seen in 14+ days and add them to removedNodes.json"""
        nodes_list = nodes_data.get('data', [])
        if not nodes_list:
            return

        # Load removed nodes to check if nodes are already there
        removed_data = self.load_removed_nodes()
        if not removed_data:
            removed_data = {
                "timestamp": datetime.now().isoformat(),
                "data": []
            }

        removed_list = removed_data.get('data', [])
        removed_public_keys = {node.get('public_key', '') for node in removed_list if node.get('public_key')}

        # Check each repeater in nodes.json
        nodes_to_add = []
        for node in nodes_list:
            public_key = node.get('public_key', '')
            if not public_key:
                continue

            # Only process repeaters (device_role == 2)
            if node.get('device_role') != 2:
                continue

            # Skip if already in removedNodes
            if public_key in removed_public_keys:
                continue

            # Check if node hasn't been seen in 14+ days
            try:
                last_seen_str = node.get('last_seen', '')
                if not last_seen_str:
                    # No last_seen timestamp, skip
                    continue

                last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
                now = datetime.now(last_seen.tzinfo)
                days_since_seen = (now - last_seen).days

                if days_since_seen > REMOVAL_THRESHOLD_DAYS:
                    node_hex = public_key[:2].upper() if len(public_key) >= 2 else ''
                    node_name = node.get('name', 'Unknown')
                    logger.info(f"Repeater {node_hex}: {node_name} has not been seen in {days_since_seen} days (>14 days) - adding to removedNodes")
                    nodes_to_add.append(node)
                    removed_public_keys.add(public_key)  # Track to avoid duplicates in same batch

            except (ValueError, TypeError) as e:
                logger.debug(f"Error parsing last_seen timestamp for node {node.get('public_key', 'Unknown')}: {e}")
                continue

        # Add nodes to removedNodes.json if any were found
        if nodes_to_add:
            removed_list.extend(nodes_to_add)
            removed_data['data'] = removed_list
            self.save_removed_nodes(removed_data)
            logger.info(f"Added {len(nodes_to_add)} node(s) to {self.removed_nodes_file}")

    def check(self):
        """Perform a single check of nodes.json"""
        try:
            # Load nodes.json
            nodes_data = self.load_nodes()
            if not nodes_data:
                return

            # Check for new repeaters that match reserved nodes
            self.check_new_repeaters_for_reserved(nodes_data)

            # Check if removed nodes have advertised recently
            self.check_removed_nodes_for_recent_activity(nodes_data)

            # Check if repeaters haven't been seen in 14+ days and add to removedNodes
            self.check_nodes_for_removal(nodes_data)

        except Exception as e:
            logger.error(f"Error in node watcher check: {e}")

    def run(self):
        """Run the watcher continuously"""
        logger.info("Starting node watcher...")

        # Perform initial check
        self.check()

        # Continuous monitoring loop
        while True:
            try:
                current_size = os.path.getsize(self.nodes_file) if os.path.exists(self.nodes_file) else 0
                if current_size > 0:
                    # Process only new data
                    self.check()
                time.sleep(5)  # Check every 5 seconds
            except KeyboardInterrupt:
                logger.info("Node watcher stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in watcher loop: {e}")
                time.sleep(CHECK_INTERVAL)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Node watcher')
    parser.add_argument('--watch', action='store_true', help='Watch nodes.json for changes and update reservedNodes.json and removedNodes.json continuously')

    args = parser.parse_args()

    # Load config
    config = load_config("config.ini")

    # Get file paths from [discord] section, with fallback to defaults
    nodes_file = config.get("discord", "nodes_file", fallback="nodes.json")
    removed_nodes_file = config.get("discord", "removed_nodes_file", fallback="removedNodes.json")
    reserved_nodes_file = config.get("discord", "reserved_nodes_file", fallback="reservedNodes.json")
    owners_file = config.get("discord", "owners_file", fallback="repeaterOwners.json")

    logger.info(f"Using nodes_file: {nodes_file}")
    logger.info(f"Using removed_nodes_file: {removed_nodes_file}")
    logger.info(f"Using reserved_nodes_file: {reserved_nodes_file}")
    logger.info(f"Using owners_file: {owners_file}")

    watcher = NodeWatcher(nodes_file, reserved_nodes_file, removed_nodes_file, owners_file)

    if args.watch:
        # Watch mode - continuously monitor nodes.json
        watcher.run()
    else:
        # One-time check
        watcher.check()


if __name__ == "__main__":
    main()
