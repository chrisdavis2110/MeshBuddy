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
from typing import Set, Dict, List, Optional

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Configuration
NODES_FILE = "nodes.json"
RESERVED_NODES_FILE = "reservedNodes.json"
REMOVED_NODES_FILE = "removedNodes.json"
CHECK_INTERVAL = 60  # Check every 60 seconds
RECENT_DAYS = 1  # Consider "recently advertised" if last_seen within 7 days
REMOVAL_THRESHOLD_DAYS = 14  # Add nodes to removedNodes if not seen in 14+ days


class NodeWatcher:
    """Watches nodes.json for changes and manages reserved/removed nodes"""

    def __init__(self):
        self.known_node_keys: Set[str] = set()
        self.last_file_mtime = 0
        self.processed_lines = 0

    def load_nodes(self) -> Optional[Dict]:
        """Load nodes.json and return the data"""
        # Retry logic to handle race conditions when file is being written
        max_retries = 3
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                if not os.path.exists(NODES_FILE):
                    logger.warning(f"{NODES_FILE} not found")
                    return None

                # Check if file is empty before trying to parse
                if os.path.getsize(NODES_FILE) == 0:
                    if attempt < max_retries - 1:
                        logger.debug(f"{NODES_FILE} is empty, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.warning(f"{NODES_FILE} is empty after {max_retries} attempts")
                        return None

                with open(NODES_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{NODES_FILE} appears empty, retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.warning(f"{NODES_FILE} is empty after {max_retries} attempts")
                            return None

                    # Parse JSON from content string
                    return json.loads(content)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error parsing {NODES_FILE} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error parsing {NODES_FILE}: {e}")
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error loading {NODES_FILE} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error loading {NODES_FILE}: {e}")
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
                if not os.path.exists(RESERVED_NODES_FILE):
                    logger.debug(f"{RESERVED_NODES_FILE} not found")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }

                # Check if file is empty before trying to parse
                if os.path.getsize(RESERVED_NODES_FILE) == 0:
                    if attempt < max_retries - 1:
                        logger.debug(f"{RESERVED_NODES_FILE} is empty, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.debug(f"{RESERVED_NODES_FILE} is empty after {max_retries} attempts")
                        return {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }

                with open(RESERVED_NODES_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{RESERVED_NODES_FILE} appears empty, retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.debug(f"{RESERVED_NODES_FILE} is empty after {max_retries} attempts")
                            return {
                                "timestamp": datetime.now().isoformat(),
                                "data": []
                            }

                    # Parse JSON from content string (not file handle)
                    return json.loads(content)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error parsing {RESERVED_NODES_FILE} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error parsing {RESERVED_NODES_FILE}: {e}")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error loading {RESERVED_NODES_FILE} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error loading {RESERVED_NODES_FILE}: {e}")
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
            with open(RESERVED_NODES_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Updated {RESERVED_NODES_FILE}")
        except Exception as e:
            logger.error(f"Error saving {RESERVED_NODES_FILE}: {e}")

    def load_removed_nodes(self) -> Optional[Dict]:
        """Load removedNodes.json and return the data"""
        # Retry logic to handle race conditions when file is being written
        max_retries = 3
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                if not os.path.exists(REMOVED_NODES_FILE):
                    logger.debug(f"{REMOVED_NODES_FILE} not found")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }

                # Check if file is empty before trying to parse
                if os.path.getsize(REMOVED_NODES_FILE) == 0:
                    if attempt < max_retries - 1:
                        logger.debug(f"{REMOVED_NODES_FILE} is empty, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.debug(f"{REMOVED_NODES_FILE} is empty after {max_retries} attempts")
                        return {
                            "timestamp": datetime.now().isoformat(),
                            "data": []
                        }

                with open(REMOVED_NODES_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        if attempt < max_retries - 1:
                            logger.debug(f"{REMOVED_NODES_FILE} appears empty, retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            logger.debug(f"{REMOVED_NODES_FILE} is empty after {max_retries} attempts")
                            return {
                                "timestamp": datetime.now().isoformat(),
                                "data": []
                            }

                    # Parse JSON from content string (not file handle)
                    return json.loads(content)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error parsing {REMOVED_NODES_FILE} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error parsing {REMOVED_NODES_FILE}: {e}")
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "data": []
                    }
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"Error loading {REMOVED_NODES_FILE} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(f"Error loading {REMOVED_NODES_FILE}: {e}")
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
            with open(REMOVED_NODES_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Updated {REMOVED_NODES_FILE}")
        except Exception as e:
            logger.error(f"Error saving {REMOVED_NODES_FILE}: {e}")

    def get_node_hex_prefix(self, node: Dict) -> Optional[str]:
        """Extract hex prefix (first 2 chars) from node's public_key"""
        public_key = node.get('public_key', '')
        if public_key and len(public_key) >= 2:
            return public_key[:2].upper()
        return None

    def is_node_recently_seen(self, node: Dict, days: int = RECENT_DAYS) -> bool:
        """Check if a node has been seen recently (within the last N days)"""
        try:
            last_seen_str = node.get('last_seen', '')
            if not last_seen_str:
                return False

            last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
            now = datetime.now(last_seen.tzinfo)
            days_ago = (now - last_seen).days

            return days_ago <= days
        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing last_seen timestamp '{last_seen_str}': {e}")
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

        # If this is the first check, initialize known_node_keys
        if not self.known_node_keys:
            self.known_node_keys = current_node_keys.copy()
            logger.info(f"Initialized node watcher with {len(self.known_node_keys)} existing nodes")
            return

        # Find new nodes
        new_node_keys = current_node_keys - self.known_node_keys

        if new_node_keys:
            logger.info(f"Found {len(new_node_keys)} new node(s)")

            # Load reserved nodes
            reserved_data = self.load_reserved_nodes()
            if not reserved_data:
                return

            reserved_list = reserved_data.get('data', [])
            if not reserved_list:
                # No reserved nodes, nothing to check
                self.known_node_keys = current_node_keys.copy()
                return

            # Collect hex prefixes of new repeaters
            new_repeater_hexes = set()
            for public_key in new_node_keys:
                node = current_nodes_map.get(public_key)
                if not node:
                    continue

                # Only process repeaters (device_role == 2)
                if node.get('device_role') != 2:
                    continue

                node_hex = self.get_node_hex_prefix(node)
                if node_hex:
                    new_repeater_hexes.add(node_hex)

            # Remove reserved nodes that match any new repeater hex
            if new_repeater_hexes:
                updated_reserved_list = []
                removed_any = False

                for reserved_node in reserved_list:
                    reserved_prefix = reserved_node.get('prefix', '').upper()
                    if reserved_prefix in new_repeater_hexes:
                        logger.info(f"New repeater {reserved_prefix} detected - removing from reserved list: {reserved_node.get('name', 'Unknown')}")
                        removed_any = True
                        # Don't add to updated_reserved_list (remove it)
                    else:
                        updated_reserved_list.append(reserved_node)

                if removed_any:
                    reserved_data['data'] = updated_reserved_list
                    self.save_reserved_nodes(reserved_data)

            # Update known_node_keys
            self.known_node_keys = current_node_keys.copy()
        else:
            # No new nodes, but still update known_node_keys in case nodes were removed externally
            self.known_node_keys = current_node_keys.copy()

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
                    node_hex = self.get_node_hex_prefix(current_node)
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
                    node_hex = self.get_node_hex_prefix(node)
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
            logger.info(f"Added {len(nodes_to_add)} node(s) to {REMOVED_NODES_FILE}")

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
                current_size = os.path.getsize(NODES_FILE) if os.path.exists(NODES_FILE) else 0
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

    watcher = NodeWatcher()

    if args.watch:
        # Watch mode - continuously monitor nodes.json
        watcher.run()
    else:
        # One-time check
        watcher.check()


if __name__ == "__main__":
    main()
