#!/usr/bin/python
"""
MeshBuddy Discord Bot - Main Entry Point

This is the main entry point for the bot. All functionality has been
refactored into separate modules:
- bot/core.py: Bot initialization, config, constants
- bot/utils.py: Utility functions
- bot/helpers.py: Helper functions (QR codes, roles, ownership)
- bot/tasks.py: Background tasks
- bot/events.py: Event handlers
- bot/commands/: Command modules (repeater, management, utility, admin)
"""

# Import bot core (bot instance) - must be first to avoid namespace conflicts
from bot.core import bot as bot_instance

# Import bot events (registers all event handlers)
# Note: Importing bot.events and bot.commands registers handlers/commands with the bot instance
import bot.events  # This registers all event handlers
import bot.commands  # This registers all commands

if __name__ == "__main__":
    bot_instance.run()
