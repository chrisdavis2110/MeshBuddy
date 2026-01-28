"""
Command History Tracking Module

Tracks command usage history and relevant events to prevent spam.
Commands can be used again if:
- A new node was added
- A new reservation was made
- A reservation was released
- It's a different day
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Set
from bot.core import logger


class CommandHistoryTracker:
    """Tracks command usage history and relevant events per category"""

    def __init__(self, history_file: str = "command_history.json"):
        self.history_file = history_file
        self.history: Dict[str, Dict] = {}
        self._load_history()

    def _load_history(self):
        """Load command history from file"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    self.history = json.load(f)
            except Exception as e:
                logger.error(f"Error loading command history: {e}")
                self.history = {}
        else:
            self.history = {}

    def _save_history(self):
        """Save command history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving command history: {e}")

    def _get_category_key(self, category_id: int) -> str:
        """Get storage key for a category"""
        return str(category_id)

    def _get_today_date(self) -> str:
        """Get today's date as YYYY-MM-DD string"""
        return datetime.now(timezone.utc).date().isoformat()

    def _get_category_data(self, category_id: int) -> Dict:
        """Get or create category data structure"""
        category_key = self._get_category_key(category_id)
        if category_key not in self.history:
            self.history[category_key] = {
                "last_commands": {},
                "last_date": None,
                "events": {
                    "new_node_added": False,
                    "reservation_made": False,
                    "reservation_released": False
                }
            }
        return self.history[category_key]

    def can_execute_command(self, command_name: str, category_id: int) -> tuple[bool, Optional[str]]:
        """
        Check if a command can be executed based on history and events.

        Returns:
            (can_execute: bool, reason: Optional[str])
        """
        category_data = self._get_category_data(category_id)
        today = self._get_today_date()

        # Check if it's a new day
        last_date = category_data.get("last_date")
        if last_date != today:
            # New day - reset events and allow command
            category_data["last_date"] = today
            category_data["events"] = {
                "new_node_added": False,
                "reservation_made": False,
                "reservation_released": False
            }
            self._save_history()
            return True, None

        # Check if command was used today
        last_commands = category_data.get("last_commands", {})
        last_command_time = last_commands.get(command_name)

        if last_command_time is None:
            # Command never used before - allow it
            return True, None

        # Check if command was used today
        try:
            last_command_date = datetime.fromisoformat(last_command_time).date()
            if last_command_date != datetime.now(timezone.utc).date():
                # Command was used on a different day - allow it (first use today)
                return True, None
        except (ValueError, TypeError):
            # Invalid date format - allow it to be safe
            return True, None

        # Command was already used today - check events based on command type
        events = category_data.get("events", {})

        if command_name == "list":
            # /list can be used if: new node, new reservation, removed reservation
            if events.get("new_node_added") or events.get("reservation_made") or events.get("reservation_released"):
                return True, None
            return False, "No changes detected since last use. Scroll up to look at the list. Use `/list` again when a new node is added, a reservation is made/released, or tomorrow."

        elif command_name == "rlist":
            # /rlist can be used if: new reservation, released reservation
            if events.get("reservation_made") or events.get("reservation_released"):
                return True, None
            return False, "No changes detected since last use. Scroll up to look at the list. Use `/rlist` again when a reservation is made/released, or tomorrow."

        elif command_name == "dupes":
            # /dupes can be used if: new node (duplicates could change)
            if events.get("new_node_added"):
                return True, None
            return False, "No changes detected since last use. Scroll up to look at the list. Use `/dupes` again when a new node is added or tomorrow."

        elif command_name == "offline":
            # /offline can be used if: new node, new reservation, removed reservation
            if events.get("new_node_added") or events.get("reservation_made") or events.get("reservation_released"):
                return True, None
            return False, "No changes detected since last use. Scroll up to look at the list. Use `/offline` again when a new node is added or tomorrow."

        # Unknown command - allow it
        return True, None

    def record_command(self, command_name: str, category_id: int):
        """Record that a command was executed"""
        category_data = self._get_category_data(category_id)
        category_data["last_commands"][command_name] = datetime.now(timezone.utc).isoformat()
        self._save_history()

    def mark_new_node_added(self, category_id: int):
        """Mark that a new node was added"""
        category_data = self._get_category_data(category_id)
        category_data["events"]["new_node_added"] = True
        self._save_history()

    def mark_reservation_made(self, category_id: int):
        """Mark that a reservation was made"""
        category_data = self._get_category_data(category_id)
        category_data["events"]["reservation_made"] = True
        self._save_history()

    def mark_reservation_released(self, category_id: int):
        """Mark that a reservation was released"""
        category_data = self._get_category_data(category_id)
        category_data["events"]["reservation_released"] = True
        self._save_history()

    def reset_events(self, category_id: int):
        """Reset all events for a category (called after command execution)"""
        category_data = self._get_category_data(category_id)
        category_data["events"] = {
            "new_node_added": False,
            "reservation_made": False,
            "reservation_released": False
        }
        self._save_history()


# Global instance
command_history = CommandHistoryTracker()
