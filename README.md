<div align="center">
  <img src="meshbuddy-emojis/meshbuddy.png" alt="MeshBuddy" width="200"/>
</div>

# MeshBuddy

A Discord bot for managing and monitoring MeshCore network repeaters and devices.

## What MeshBuddy Does

MeshBuddy is a comprehensive Discord bot that provides real-time monitoring and management capabilities for MeshCore mesh network nodes. The bot:

- **Monitors Repeaters**: Tracks active, offline, and duplicate repeater nodes in your mesh network
- **Manages Node Data**: Helps manage reserved nodes, removed nodes, and tracks node availability
- **Generates QR Codes**: Creates QR codes for easy contact addition to MeshCore devices
- **Provides Real-time Notifications**: Sends Discord alerts when new repeaters join the network
- **Updates Channel Names**: Automatically updates Discord channel names with repeater counts
- **Key Generation**: Generates MeshCore keypairs with custom hex prefixes (uses [agessaman's](https://github.com/agessaman)
[meshcore-keygen](https://github.com/agessaman/meshcore-keygen))

### Discord Bot Commands

- **`/list [days]`** - Get a list of active repeaters (default: last 7 days)
- **`/offline [days]`** - Get a list of offline repeaters (default: last 14 days)
- **`/dupes [days]`** - Get a list of duplicate repeater prefixes
- **`/open [days]`** - Get a list of unused hex keys (00-FF)
- **`/prefix <hex> [days]`** - Check if a specific hex prefix is available
- **`/stats <hex> [days]`** - Get detailed stats for a specific repeater
- **`/qr <hex>`** - Generate a QR code for adding a contact
- **`/reserve <hex> <name>`** - Reserve a hex prefix for a repeater
- **`/release <hex>`** - Release a reserved hex prefix
- **`/remove <hex>`** - Remove a repeater from the active list
- **`/rlist`** - Get a list of reserved repeaters
- **`/xlist`** - Get a list of removed repeaters
- **`/keygen <prefix>`** - Generate a MeshCore keypair with a specific prefix
- **`/help`** - Show all available commands

## Installation

### Prerequisites

- Python 3.7 or higher
- Discord Bot Token (create one at https://discord.com/developers/applications)
- Access to a MeshCore MQTT broker API or use the provided `meshupdater.py` script

### Setup Steps

1. **Clone or download the repository:**
   ```bash
   git clone https://github.com/chrisdavis2110/MeshBuddy.git
   cd MeshBuddy
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the bot:**
   ```bash
   cp exampleconfig.ini config.ini
   ```

   Edit `config.ini` with your settings:
   ```ini
   [discord]
   token = <YOUR_DISCORD_BOT_TOKEN>
   repeater_channel_id = <DISCORD_CHANNEL_ID>
   messenger_channel_id = <DISCORD_CHANNEL_ID>

   [meshcore]
   mqtt_api = <YOUR_MQTT_API_URL>
   ```

5. **Set up Discord Bot:**
   - Create a Discord application at https://discord.com/developers/applications
   - Create a bot and copy the token
   - Invite the bot to your server with appropriate permissions (Send Messages, Embed Links, Attach Files, Use Slash Commands)

6. **Get your nodes.json file:**

   You need a `nodes.json` file to run the bot. You have two options:

   **Option A: Use your own MQTT broker**
   - If you have access to a MeshCore MQTT broker, subscribe to the broker's packets topic
   - Decode the data from your MQTT broker and create `nodes.json`
   - Create a symlink `ln -s path/to/MQTT/nodes.json path/to/MeshBuddy/nodes.json`

   **Option B: Use the meshupdater.py script**
   - The `meshupdater.py` script fetches data from the configured MQTT API endpoint
   - Run it to generate your initial `nodes.json` file:
     ```bash
     python meshupdater.py
     ```
   - This will create `nodes.json` in the current directory
   - Add a cron job to run `meshupdater.py` every 15-30 mins

## Running the Bot

### Manual Execution

To run the Discord bot manually:

```bash
python hikari_bot.py
```

### Updating Node Data

To update the `nodes.json` file with fresh data from your MQTT broker:

```bash
python meshupdater.py
```

## Using Service Files

MeshBuddy can be run as a system service for automatic startup and continuous operation. Service files are provided for Linux (systemd).

### Linux (systemd)

The bot can run as a systemd service on Linux systems:

1. **Copy the service file:**
   ```bash
   sudo cp meshbuddy.service /etc/systemd/system/
   ```

2. **Edit the service file** to match your installation paths:
   ```bash
   sudo nano /etc/systemd/system/meshbuddy.service
   ```

   Update the following lines:
   - `WorkingDirectory` - Path to your MeshBuddy directory
   - `ExecStart` - Path to your Python executable and script
   - `User` - User to run the service as

3. **Enable and start the service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable meshbuddy
   sudo systemctl start meshbuddy
   ```

4. **Check service status:**
   ```bash
   sudo systemctl status meshbuddy
   ```

5. **View logs:**
   ```bash
   journalctl -u meshbuddy -f
   ```

6. **Stop the service:**
   ```bash
   sudo systemctl stop meshbuddy
   ```

## Data Files

The bot uses several JSON files to manage node data:

- **`nodes.json`** - Main data file containing all network nodes. This file is required and can be generated using `meshupdater.py` or provided from your own MQTT broker.
- **`reservedNodes.json`** - Tracks reserved hex prefixes for repeaters
- **`removedNodes.json`** - Tracks repeaters that have been removed or are offline
- **`updated.json`** - Comparison results showing new, removed, and duplicate entries
- **`update_summary.txt`** - Human-readable summary of the last update

## Node Watcher Service

The `node_watcher.py` script runs as a separate service and automatically:

- Removes reserved nodes from the reserved list when a repeater with the same hex prefix is detected
- Removes nodes from `removedNodes.json` if they've advertised recently
- Adds repeaters to `removedNodes.json` if they haven't been seen in over 14 days

This script can be run manually or as a systemd service on Linux. Add the `--watch` flag to follow changes to `nodes.json`

## Troubleshooting

- **Bot not responding**: Check that the Discord token is correct in `config.ini`
- **No node data**: Ensure `nodes.json` exists and contains valid data. Run `meshupdater.py` to generate it.
- **Service won't start**: Check the log files in the `logs/` directory for error messages
- **Permission errors**: Ensure the service user has read/write access to the MeshBuddy directory and log files

## License

See LICENSE file for details.
