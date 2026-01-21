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
- **Provides Real-time Notifications**: Sends Discord alerts when new repeaters join the network with location links (if available)
- **Updates Channel Names**: Automatically updates Discord channel name with repeater counts (online, offline, dead, reserved)
- **Key Generation**: Generates MeshCore keypairs with custom hex prefixes (uses [agessaman's](https://github.com/agessaman)
[meshcore-keygen](https://github.com/agessaman/meshcore-keygen))
- **Data Source Selection**: Automatically uses MQTT or API polling based on configuration

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
   repeater_status_channel_id = <DISCORD_CHANNEL_ID>
   bot_messenger_channel_id = <DISCORD_CHANNEL_ID>
   bot_owner_id = <YOUR_USER_ID>
   repeater_owner_role_id = <ROLE_ID>

   [api]
   api_enabled = False
   api_url = https://api.letsmesh.net/api/nodes?region=<IATA>
   api_poll_interval = 900

   [mqtt]
   mqtt_enabled = True
   mqtt_url = <MQTT_BROKER_URL>
   mqtt_port = <PORT>
   mqtt_username = <USERNAME>
   mqtt_password = <PASSWORD>
   mqtt_transport = websockets
   mqtt_ws_path = /
   mqtt_tls = True
   mqtt_topics = meshcore/<IATA>/+/packets

   [meshmap]
   url = https://analyzer.letsmesh.net/map
   ```

   **Data Source Configuration:**
   - Set `mqtt_enabled = True` in `[mqtt]` section to use MQTT (recommended for real-time updates)
   - Set `api_enabled = True` in `[api]` section to use API polling (fallback if MQTT is unavailable)
   - If both are enabled, MQTT takes priority
   - If neither is enabled, the bot will run but won't receive node updates

5. **Set up Discord Bot:**
   - Create a Discord application at https://discord.com/developers/applications
   - Create a bot and copy the token
   - Invite the bot to your server with appropriate permissions (Send Messages, Embed Links, Attach Files, Use Slash Commands, Manage Messages, Manage Channels, Manage Roles, View Channels)
   - Get the channel IDs for:
     - `repeater_status_channel_id`: Channel where repeater status counts will be displayed in the channel name
     - `bot_messenger_channel_id`: Channel where new node notifications will be sent

6. **Data Files:**
   The bot will automatically initialize required JSON files on startup if they don't exist:
   - `nodes.json` - Main data file containing all network nodes (created by MQTT subscriber or API polling)
   - `reservedNodes.json` - Tracks reserved hex prefixes for repeaters
   - `repeaterOwners.json` - Tracks repeater ownership information
   - `offReserved.json` - Tracks reserved nodes that have become active

## Running the Bot

### Manual Execution

To run the Discord bot manually:

```bash
python hikari_bot.py
```

The bot will:
- Initialize required JSON files if they don't exist
- Start MQTT subscriber (if `mqtt_enabled = True`) or API polling (if `api_enabled = True`)
- Begin monitoring for new nodes and updating channel names
- Process all Discord commands

### Data Source

The bot automatically selects its data source based on configuration:

- **MQTT (Recommended)**: Real-time updates via MQTT broker subscription
  - Set `mqtt_enabled = True` in `[mqtt]` section
  - The bot subscribes to configured MQTT topics and processes packets in real-time
  - Creates/updates `nodes.json` automatically

- **API Polling**: Periodic updates via HTTP API
  - Set `api_enabled = True` in `[api]` section (and `mqtt_enabled = False`)
  - Polls the API at the configured interval (`api_poll_interval`)
  - Creates/updates `nodes.json` automatically

- **No Data Source**: Bot runs but won't receive node updates
  - Both `mqtt_enabled` and `api_enabled` are `False`
  - Bot can still process commands using existing `nodes.json` file

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

The bot uses several JSON files to manage node data. All files are automatically initialized on startup if they don't exist:

- **`nodes.json`** - Main data file containing all network nodes. Automatically created/updated by MQTT subscriber or API polling. Contains all nodes from all regions in a single file.
- **`reservedNodes.json`** - Tracks reserved hex prefixes for repeaters. Users can reserve prefixes before deploying repeaters.
- **`repeaterOwners.json`** - Tracks repeater ownership information. Links Discord users to their repeaters.
- **`offReserved.json`** - Tracks reserved nodes that have become active. When a reserved repeater goes online, it's moved here.
- **`removedNodes.json`** - Tracks repeaters that have been removed or are offline (optional, created when nodes are removed via `/remove` command)

All files use the same structure:
```json
{
  "timestamp": "2026-01-21T09:31:50.444444Z",
  "data": [...]
}
```

## Features

### Automatic Node Monitoring

The bot automatically:
- Monitors `nodes.json` for new nodes and sends Discord notifications
- Includes location links in new node alerts (if node has location data) pointing to the configured meshmap
- Updates the repeater status channel name with counts (✅ online, ⚠️ offline, ❌ dead, ⏳ reserved)
- Processes all nodes from a single `nodes.json` file

### Node Watcher (Optional)

The `node_watcher.py` script can run as a separate service and automatically:

- Moves reserved nodes to `offReserved.json` when a repeater with the same hex prefix is detected
- Removes nodes from `removedNodes.json` if they've advertised recently
- Adds repeaters to `removedNodes.json` if they haven't been seen in over 14 days

This script can be run manually or as a systemd service on Linux. Add the `--watch` flag to follow changes to `nodes.json`

## Configuration Details

### Discord Section
- `token`: Your Discord bot token
- `repeater_status_channel_id`: Channel where repeater counts are displayed in the channel name
- `bot_messenger_channel_id`: Channel where new node notifications are sent
- `bot_owner_id`: Your Discord user ID (for admin commands)
- `repeater_owner_role_id`: Role ID to assign to users who claim repeaters

### API Section
- `api_enabled`: Set to `True` to enable API polling mode
- `api_url`: API endpoint URL for fetching node data
- `api_poll_interval`: How often to poll the API (in seconds, default: 900)

### MQTT Section
- `mqtt_enabled`: Set to `True` to enable MQTT mode (takes priority over API)
- `mqtt_url`: MQTT broker URL
- `mqtt_port`: MQTT broker port
- `mqtt_username`: MQTT username
- `mqtt_password`: MQTT password
- `mqtt_transport`: Transport type (`websockets` or `tcp`)
- `mqtt_ws_path`: WebSocket path (if using websockets)
- `mqtt_tls`: Enable TLS (`True` or `False`)
- `mqtt_topics`: Comma-separated list of MQTT topics to subscribe to

### MeshMap Section
- `url`: Base URL for the mesh map. Location links in new node notifications will use this URL with `?lat=...&long=...` appended.

## Troubleshooting

- **Bot not responding**: Check that the Discord token is correct in `config.ini`
- **No node data**: Ensure MQTT or API is enabled in config. The bot will automatically create `nodes.json` when it receives data.
- **Files not initializing**: Check that the bot has write permissions in the MeshBuddy directory
- **Service won't start**: Check the log files in the `logs/` directory for error messages
- **Permission errors**: Ensure the service user has read/write access to the MeshBuddy directory and log files
- **MQTT connection fails**: Check MQTT credentials and network connectivity. The bot will fall back to API polling if configured.

## License

See LICENSE file for details.
