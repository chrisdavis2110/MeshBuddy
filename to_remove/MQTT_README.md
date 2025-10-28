# MQTT Reader for MeshCore Network

This tool connects directly to the MQTT broker and collects node data to create a `mqttnodes.json` file.

## Overview

The MQTT reader connects to `mqtt.wcmesh.com` on port 883 (TLS without certificate verification) and subscribes to mesh network topics to collect device information. It uses the meshcore-decoder logic (implemented in Python) to decode MeshCore packets.

## Prerequisites

1. Python 3.7+
2. MQTT broker credentials (username/password)
3. paho-mqtt library

## Installation

1. Install the required package:
```bash
pip install -r requirements_mqtt.txt
```

Or install directly:
```bash
pip install paho-mqtt
```

## Usage

### Basic Usage

```bash
python mqttreader.py
```

This will prompt for credentials or use default ones if configured.

### With Credentials

```bash
python mqttreader.py --username your_username --password your_password
```

### Advanced Options

```bash
python mqttreader.py \
  --username your_username \
  --password your_password \
  --duration 120 \
  --output mynodes.json
```

### Options

- `--username`: MQTT username (required for password-protected brokers)
- `--password`: MQTT password (required for password-protected brokers)
- `--duration`: How long to collect data in seconds (default: 60)
- `--output`: Output filename (default: mqttnodes.json)

## What It Does

1. **Connects** to the MQTT broker at `mqtt.wcmesh.com:883`
2. **Subscribes** to the following topics:
   - `msh/2/json/+` - Node info packets
   - `msh/2/e/+/+` - Encrypted packets
   - `msh/2/c/+/+` - Compressed packets
   - `msh/2/config/+` - Config packets
   - `msh/2/nodeinfo/+` - Node information
3. **Collects** data for the specified duration
4. **Decodes** packets using the MeshCore decoder
5. **Saves** all collected node data to `mqttnodes.json`

## Output Format

The output JSON file follows the same format as your existing `nodes.json`:

```json
{
  "timestamp": "2025-01-23T12:00:00.000000",
  "data": [
    {
      "public_key": "015806F76D49EFD367F052C6C913759AA184D53BC8F3EFC1D03F419371B5A405",
      "name": "Device Name",
      "device_role": 1,
      "regions": ["LAX"],
      "first_seen": "2025-01-23T10:00:00.000000",
      "last_seen": "2025-01-23T12:00:00.000000",
      "is_mqtt_connected": true,
      "decoded_payload": {
        "mode": "Companion",
        "name": "Device Name",
        "flags": 129,
        "public_key": "015806F76D49EFD367F052C6C913759AA184D53BC8F3EFC1D03F419371B5A405"
      },
      "location": {
        "latitude": 34.0522,
        "longitude": -118.2437
      }
    }
  ]
}
```

## Device Roles

- `device_role: 1` - Companion devices
- `device_role: 2` - Repeater devices
- `device_role: 3` - Room Server devices

## Testing the Decoder

You can test the packet decoder independently:

```bash
python decoder.py <hex_packet>

# Example:
python decoder.py 11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C
```

## Troubleshooting

### Connection Issues

If you're having trouble connecting:

1. Check that port 883 is accessible
2. Verify your credentials are correct
3. Ensure the broker is not rate-limiting your connection

### No Data Collected

If no nodes are collected:

1. Increase the `--duration` time
2. Check that the mesh network is active
3. Verify you're subscribing to the correct topics
4. Check the console logs for error messages

### Packet Decoding Issues

If packets aren't decoding correctly:

1. The decoder is based on meshcore-decoder logic
2. Packet formats may vary by firmware version
3. Raw packet data is preserved in `decoded_payload` for debugging

## Integration with Existing Code

You can use the generated `mqttnodes.json` with your existing MeshBuddy codebase:

```python
from mqttreader import MeshMQTTReader

# Create and configure reader
reader = MeshMQTTReader(
    broker_host="mqtt.wcmesh.com",
    broker_port=883,
    username="your_username",
    password="your_password"
)

# Connect and collect data
reader.connect()
reader.start()
reader.collect_data(duration=120)  # Collect for 2 minutes
reader.save_to_json("mqttnodes.json")
reader.stop()
```

## Security Notes

- The connection uses TLS but with certificate verification disabled (`CERT_NONE`)
- Credentials are passed as command-line arguments (consider using environment variables)
- The broker is password-protected

## Example Session

```bash
$ python mqttreader.py --username myuser --password mypass --duration 60

Connecting to MQTT broker mqtt.wcmesh.com:883
Connected to MQTT broker mqtt.wcmesh.com:883
Subscribed to topics with QoS: 1
Collecting data for 60 seconds...
Updated node: Repeater1 (015806F76D49EFD367F052C6C913759AA184D53BC8F3EFC1D03F419371B5A405)
Updated node: Companion1 (020C4F3361F5262803D7601E6A3B09F434ECE30A12B360ECDB31BC3C39A27660)
Finished collecting data. Found 45 nodes.
Saved 45 nodes to mqttnodes.json

Summary:
  Nodes found: 45
  Output file: mqttnodes.json
```

## References

- [MeshCore Decoder](https://github.com/michaelhart/meshcore-decoder) - TypeScript implementation
- [Paho MQTT Python Client](https://github.com/eclipse/paho.mqtt.python) - MQTT client library
