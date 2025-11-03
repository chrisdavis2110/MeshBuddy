# macOS Service Setup for MeshBuddy

This guide explains how to install and manage the MeshBuddy services on macOS using `launchd`.

## Service Files

- `com.meshbuddy.bot.plist` - Discord bot service (hikari_bot.py)
- `com.meshbuddy.nodewatcher.plist` - Node watcher service (node_watcher.py)

## Installation

1. **Create the logs directory** (if it doesn't exist):
   ```bash
   mkdir -p /Users/chris/Documents/VSCode/meshcore/MeshBuddy/logs
   ```

2. **Install the services** (run from the MeshBuddy directory):
   ```bash
   # Install Discord bot service
   sudo launchctl load -w /Users/chris/Documents/VSCode/meshcore/MeshBuddy/com.meshbuddy.bot.plist

   # Install node watcher service
   sudo launchctl load -w /Users/chris/Documents/VSCode/meshcore/MeshBuddy/com.meshbuddy.nodewatcher.plist
   ```

   Note: If you want to run as your user (not root), move the plist files to `~/Library/LaunchAgents/` and use `launchctl load` without sudo.

## Management Commands

### Start services
```bash
sudo launchctl start com.meshbuddy.bot
sudo launchctl start com.meshbuddy.nodewatcher
```

### Stop services
```bash
sudo launchctl stop com.meshbuddy.bot
sudo launchctl stop com.meshbuddy.nodewatcher
```

### Check service status
```bash
sudo launchctl list | grep meshbuddy
```

### Unload services (to stop and remove)
```bash
sudo launchctl unload -w /Users/chris/Documents/VSCode/meshcore/MeshBuddy/com.meshbuddy.bot.plist
sudo launchctl unload -w /Users/chris/Documents/VSCode/meshcore/MeshBuddy/com.meshbuddy.nodewatcher.plist
```

### View logs
```bash
# Bot logs
tail -f /Users/chris/Documents/VSCode/meshcore/MeshBuddy/logs/bot.log
tail -f /Users/chris/Documents/VSCode/meshcore/MeshBuddy/logs/bot.error.log

# Node watcher logs
tail -f /Users/chris/Documents/VSCode/meshcore/MeshBuddy/logs/node_watcher.log
tail -f /Users/chris/Documents/VSCode/meshcore/MeshBuddy/logs/node_watcher.error.log
```

## Running as User (Recommended)

If you prefer to run these as your user instead of root:

1. **Copy plist files to user LaunchAgents directory:**
   ```bash
   cp com.meshbuddy.bot.plist ~/Library/LaunchAgents/
   cp com.meshbuddy.nodewatcher.plist ~/Library/LaunchAgents/
   ```

2. **Load the services:**
   ```bash
   launchctl load -w ~/Library/LaunchAgents/com.meshbuddy.bot.plist
   launchctl load -w ~/Library/LaunchAgents/com.meshbuddy.nodewatcher.plist
   ```

3. **Management commands** (without sudo):
   ```bash
   launchctl start com.meshbuddy.bot
   launchctl start com.meshbuddy.nodewatcher
   launchctl stop com.meshbuddy.bot
   launchctl stop com.meshbuddy.nodewatcher
   launchctl unload -w ~/Library/LaunchAgents/com.meshbuddy.bot.plist
   launchctl unload -w ~/Library/LaunchAgents/com.meshbuddy.nodewatcher.plist
   ```

## Notes

- Services will automatically start on system boot (due to `RunAtLoad` being true)
- Services will automatically restart if they crash (due to `KeepAlive` being true)
- Make sure the virtual environment path is correct in the plist files
- Logs are written to the `logs/` directory in the MeshBuddy folder
