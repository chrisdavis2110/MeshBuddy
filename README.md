# MeshBuddy

A Discord bot for managing and monitoring MeshCore network repeaters and devices.

## Overview

MeshBuddy is a comprehensive tool that bridges MeshCore network data with Discord, providing real-time monitoring and management capabilities for mesh network nodes. It fetches data from a MQTT API and exposes various commands through a Discord bot interface.

## Features

### Discord Bot Commands

- **`/list [days]`** - Get a list of active repeaters (default: last 7 days)
- **`/offline [days]`** - Get a list of offline repeaters (default: last 7 days)
- **`/dupes`** - Get a list of duplicate repeater prefixes
- **`/open`** - Get a list of unused hex keys (00-FF)
- **`/prefix <hex>`** - Check if a specific hex prefix is available
- **`/stats <hex>`** - Get detailed stats for a specific repeater

### Data Management

- **MQTT Integration** - Fetches real-time data from https://analyzer.letsme.sh API
- **Local Data Storage** - Maintains local JSON files for offline access
- **Data Comparison** - Tracks changes between data updates


## Installation

### Prerequisites

- Python 3.7+
- Discord Bot Token
- Access to https://analyzer.letsme.sh API

### Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd MeshBuddy
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv meshbuddy
   source meshbuddy/bin/activate  # On Windows: meshbuddy\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install hikari-lightbulb requests
   ```

4. **Configure the bot:**
   ```bash
   cp exampleconfig.ini config.ini
   ```

   Edit `config.ini` with your settings:
   ```ini
   [discord]
   token = <YOUR_DISCORD_BOT_TOKEN>

   [meshcore]
   mqtt_api = <analyzer.letsmesh API>
   ```

5. **Set up Discord Bot:**
   - Create a Discord application at https://discord.com/developers/applications
   - Create a bot and copy the token
   - Invite the bot to your server with appropriate permissions

## Usage

### Running the Discord Bot

```bash
python hikari_bot.py
```

### Updating Node Data

```bash
python meshupdater.py
```


## Data Files

- **`nodes.json`** - Main data file containing all network nodes with timestamps
- **`updated.json`** - Comparison results showing new, removed, and duplicate entries
- **`update_summary.txt`** - Human-readable summary of the last update

## System Service

To run MeshBuddy as a system service:

1. **Copy the service file:**
   ```bash
   sudo cp meshbuddy.service /etc/systemd/system/
   ```

2. **Edit the service file** to match your installation path

3. **Enable and start the service:**
   ```bash
   sudo systemctl deamon-reload
   sudo systemctl enable meshbuddy
   sudo systemctl start meshbuddy
   ```

## API Reference

### MeshMQTTBridge Class

#### Methods

- `get_data_from_mqtt()` - Fetch data from MQTT API
- `save_data_to_json(data, filename)` - Save data to JSON file
- `load_data_from_json(filename)` - Load data from JSON file
- `compare_data(new_data, old_data)` - Compare two datasets
- `update_nodes_data()` - Complete update workflow
- `get_repeater_list(days=7)` - Get list of active repeaters
- `get_repeater_offline(days=8)` - Get list of offline repeaters
- `get_unused_keys()` - Get list of available hex keys
- `get_repeater_duplicates()` - Get list of duplicate prefixes
- `get_repeater(prefix)` - Get specific repeater information
