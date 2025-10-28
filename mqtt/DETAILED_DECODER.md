# Detailed MeshCore Decoder - TypeScript Compatible Output

## Overview

The enhanced Python decoder now produces output in the exact format matching the TypeScript [meshcore-decoder](https://github.com/michaelhart/meshcore-decoder) library.

## Usage

```python
from decoder import MeshCorePacketDecoder
import json

# Your packet hex data
hex_data = '11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C94006CE7CF682E58408DD8FCC51906ECA98EBF94A037886BDADE7ECD09FD92B839491DF3809C9454F5286D1D3370AC31A34593D569E9A042A3B41FD331DFFB7E18599CE1E60992A076D50238C5B8F85757375354522F50756765744D65736820436F75676172'

# Decode with TypeScript-compatible format
decoded = MeshCorePacketDecoder.decode_detailed(hex_data)

print(json.dumps(decoded, indent=2))
```

## Output Format

The decoder produces output matching this structure:

```json
{
  "messageHash": "75676172",
  "routeType": 0,
  "payloadType": 1,
  "payloadVersion": 0,
  "pathLength": 0,
  "path": null,
  "totalBytes": 134,
  "isValid": true,
  "payload": {
    "raw": "7E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C94006CE7CF682E58408DD8FCC51906ECA98EBF94A037886BDADE7ECD09FD92B839491DF3809C9454F5286D1D3370AC31A34593D569E9A042A3B41FD331DFFB7E18599CE1E60992A076D50238C5B8F85757375354522F50756765744D65736820436F75676172",
    "decoded": {
      "type": 4,
      "version": 0,
      "isValid": true,
      "publicKey": "7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C94006C",
      "timestamp": 1758455660,
      "signature": "FCC51906ECA98EBF94A037886BDADE7ECD09FD92B839491DF3809C9454F5286D",
      "appData": {
        "flags": 146,
        "deviceRole": 2,
        "hasLocation": true,
        "hasName": true,
        "location": {
          "latitude": 47.543968,
          "longitude": -122.108616
        },
        "name": "WW7STR/PugetMesh Cougar"
      }
    }
  }
}
```

## Field Descriptions

### Top Level Fields
- **messageHash**: Last 4 bytes of the packet in hex
- **routeType**: Routing type (0 = no response wanted)
- **payloadType**: Packet type (0=POSITION, 1=NODEINFO, etc.)
- **payloadVersion**: Version field
- **pathLength**: Number of hops in the routing path
- **path**: Array of node numbers in the routing path
- **totalBytes**: Total packet size in bytes
- **isValid**: Whether the packet is valid

### Payload Fields
- **raw**: Hexadecimal representation of the payload
- **decoded**: Parsed payload data

### Decoded Fields (NODEINFO)
- **type**: Application type (4 for NODEINFO)
- **version**: Payload version
- **isValid**: Whether payload is valid
- **publicKey**: Device's public key
- **timestamp**: Unix timestamp
- **signature**: Cryptographic signature

### AppData Fields
- **flags**: Device flags
- **deviceRole**: Role type (1=Companion, 2=Repeater, 3=Room Server)
- **hasLocation**: Whether GPS coordinates are present
- **hasName**: Whether a device name is present
- **location**: GPS coordinates with latitude/longitude
- **name**: Device name

## Accessing Fields

```python
# Get device information
device_name = decoded['payload']['decoded']['appData']['name']
device_role = decoded['payload']['decoded']['appData']['deviceRole']

# Get location
if decoded['payload']['decoded']['appData']['hasLocation']:
    location = decoded['payload']['decoded']['appData']['location']
    print(f"Device at: {location['latitude']}, {location['longitude']}")

# Get packet metadata
packet_type = decoded['payloadType']  # 0=POSITION, 1=NODEINFO, 2=TELEMETRY, 4=TEXT_MESSAGE
total_bytes = decoded['totalBytes']
```

## Comparison: Python vs TypeScript

The Python decoder now produces output that matches the TypeScript version in structure. The main differences are:

1. **Packet Structure Parsing**: Python version handles the routing and payload extraction
2. **Field Names**: Match exactly with camelCase naming
3. **Data Types**: Same types (strings, integers, booleans)

## Example Use Cases

### Discord Bot Integration

```python
from decoder import MeshCorePacketDecoder

def process_mesh_packet(hex_data: str):
    decoded = MeshCorePacketDecoder.decode_detailed(hex_data)

    if decoded and decoded['isValid']:
        app_data = decoded['payload']['decoded'].get('appData', {})

        # Post to Discord
        message = f"Device: {app_data.get('name', 'Unknown')}"
        if app_data.get('hasLocation'):
            loc = app_data['location']
            message += f"\nLocation: {loc['latitude']}, {loc['longitude']}"

        return message
```

### MQTT Integration

```python
from decoder import MeshCorePacketDecoder

def on_mqtt_message(topic, payload):
    hex_payload = payload.hex().upper()
    decoded = MeshCorePacketDecoder.decode_detailed(hex_payload)

    if decoded:
        # Store node information
        store_node_data(decoded)
```

## See Also

- Run `python3 example_usage.py` for a working example
- See `DECODER_USAGE.md` for basic usage
- See `DECODER_IMPROVEMENTS.md` for implementation details
- [TypeScript meshcore-decoder](https://github.com/michaelhart/meshcore-decoder) - Reference implementation
