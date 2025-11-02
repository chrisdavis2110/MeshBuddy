# MeshCore Packet Decoder - Python Implementation

This is a Python implementation of the [meshcore-decoder](https://github.com/michaelhart/meshcore-decoder) TypeScript library for decoding MeshCore mesh networking packets.

## Features

- **Full Packet Structure Analysis**: Decodes all MeshCore packet types (POSITION, NODEINFO, TELEMETRY, TEXT_MESSAGE)
- **Routing Information Extraction**: Decodes routing headers and hop information
- **Text Extraction**: Automatically extracts readable strings from packets
- **Protobuf Support**: Handles varint encoding used in MeshCore packets
- **Structure Analysis**: Optional detailed byte-by-byte breakdown

## Basic Usage

```python
from decoder import MeshCorePacketDecoder
import json

# Example packet from meshcore-decoder repository
hex_data = '11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C94006CE7CF682E58408DD8FCC51906ECA98EBF94A037886BDADE7ECD09FD92B839491DF3809C9454F5286D1D3370AC31A34593D569E9A042A3B41FD331DFFB7E18599CE1E60992A076D50238C5B8F85757375354522F50756765744D65736820436F75676172'

# Decode the packet
packet = MeshCorePacketDecoder.decode_packet(hex_data)

print(json.dumps(packet, indent=2))
```

### Output

```json
{
  "raw": "11007E7662676F7F...",
  "length": 134,
  "type": "NODEINFO",
  "type_id": 1,
  "want_response": false,
  "hop_limit": 1,
  "mode": "NodeInfo",
  "data_length": 133,
  "strings": [
    "WW7STR/PugetMesh Cougar"
  ],
  "text_strings": [
    "WW7STR/PugetMesh Cougar"
  ]
}
```

## Advanced Usage

### With Structure Analysis

Get a detailed breakdown of packet structure:

```python
packet = MeshCorePacketDecoder.decode_packet(hex_data, include_structure=True)
```

This adds a `structure` field showing:
- Header byte analysis
- Routing information
- Payload start position

### Extracting Text from Packets

The decoder automatically extracts readable ASCII strings:

```python
packet = MeshCorePacketDecoder.decode_packet(hex_data)

# Access extracted strings
if 'text_strings' in packet:
    for text in packet['text_strings']:
        print(f"Found: {text}")
```

### Command Line Interface

```bash
# Basic decoding
python decoder.py 11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C

# With structure analysis
python decoder.py 11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C --structure
```

## Packet Types

### NODEINFO (Type 1)
Device information packets containing node details:

```python
if packet['type_id'] == 1:
    print(f"Node Info Packet")
    print(f"Mode: {packet['mode']}")
    if 'strings' in packet:
        print(f"Device Name: {packet['strings'][0]}")
```

### POSITION (Type 0)
GPS location packets:

```python
if packet['type_id'] == 0:
    print(f"Location: {packet['lat']}, {packet['lon']}")
    print(f"Altitude: {packet['altitude']}")
```

### TELEMETRY (Type 2)
Telemetry data packets:

```python
if packet['type_id'] == 2:
    print(f"Telemetry Data: {packet['data_hex']}")
```

### TEXT_MESSAGE (Type 4)
Text messages (may be encrypted):

```python
if packet['type_id'] == 4:
    if packet.get('encrypted'):
        print(f"Encrypted Message: {packet['data_hex']}")
    else:
        print(f"Text: {packet['text']}")
```

## Integration with MQTT Reader

The decoder is already integrated with `mqttreader.py`:

```python
from decoder import MeshCorePacketDecoder

# In your MQTT message handler
def process_binary_packet(topic, payload):
    hex_payload = payload.hex().upper()
    decoded = MeshCorePacketDecoder.decode_packet(hex_payload)

    if decoded:
        # Extract device information
        device_name = decoded.get('strings', ['Unknown'])[0]
        print(f"Device: {device_name}")
```

## Example: Decoding a Real Packet

```python
from decoder import MeshCorePacketDecoder
import json

# Real packet from your mqttnodes.json
real_packet = "12006969A6E83EDB30023711D597CF61EBDBACA9F0C4FD1198E039DDEEAB3A9FEECAD292FE68ECFE46E899688AF626EAAF85A5AF25EDC2605B602AB1E1DF8F56C402376B5987BD7D6CDCF4511D01EE4C7918577BF1C0C74A0B516BC95732585ECED3AF90A90C927A010A022B49F3F857434D4553482E434F4D2D5665726475676F"

decoded = MeshCorePacketDecoder.decode_packet(real_packet, include_structure=True)

print("Decoded Packet:")
print(json.dumps(decoded, indent=2))

# Extract useful information
if decoded:
    print(f"\nPacket Type: {decoded['type']}")

    if 'text_strings' in decoded and decoded['text_strings']:
        print(f"Device Name: {decoded['text_strings'][-1]}")  # Last string is usually the name

    if decoded['type_id'] == 1:
        print("This is a NODEINFO packet")
        print(f"Payload Length: {decoded['data_length']} bytes")
```

## Testing

Run the test script to see examples:

```bash
python3 test_decoder.py
```

## Comparison with TypeScript Version

The TypeScript library (`@michaelhart/meshcore-decoder`) provides additional features:

- **Ed25519 Key Derivation**: WebAssembly-based cryptography
- **Message Decryption**: Decrypt GroupText and TextMessage packets
- **Full Protobuf Parsing**: Complete user field decoding

The Python version focuses on:
- Packet structure decoding
- Text extraction
- Basic field parsing
- MQTT integration

For full cryptographic features, consider using the TypeScript library or integrating with it via Node.js subprocess.

## See Also

- [meshcore-decoder TypeScript Library](https://github.com/michaelhart/meshcore-decoder)
- [MeshCore Protocol Documentation](https://meshcore.net)
- [Packet Analyzer](https://packet-analyzer.letsme.sh)
