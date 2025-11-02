# MeshCore Decoder Improvements

## Overview

Updated the Python MeshCore packet decoder (`decoder.py`) to provide enhanced functionality similar to the [meshcore-decoder](https://github.com/michaelhart/meshcore-decoder) TypeScript library.

## Key Improvements

### 1. Enhanced Packet Structure Analysis

Added comprehensive packet decoding with:

- **Varint Support**: Proper handling of protobuf-style variable-length integers
- **Routing Decoding**: Extracts routing information (hop count, node numbers)
- **Structure Analysis**: Optional detailed byte-by-byte breakdown
- **Field Extraction**: Decodes packet fields based on wire types

### 2. Text Extraction

Automatic extraction of readable ASCII strings from packets, useful for finding device names and embedded text.

### 3. Improved Packet Type Handlers

Each packet type now has enhanced decoding:

- **POSITION (Type 0)**: Decodes GPS coordinates with proper byte offset handling
- **NODEINFO (Type 1)**: Extracts device information and text strings
- **TELEMETRY (Type 2)**: Handles telemetry data with hex output
- **TEXT_MESSAGE (Type 4)**: Detects encrypted vs. plain text messages

### 4. New Methods

- `read_varint()`: Decodes protobuf varints
- `read_field_number_and_wire_type()`: Extracts field metadata
- `decode_routing()`: Parses routing headers
- `extract_text_strings()`: Finds readable text
- `analyze_structure()`: Detailed structure breakdown

### 5. Enhanced CLI

Added support for structure analysis:

```bash
python decoder.py 11007E7662676F7F... --structure
```

## Example Usage

### Basic Decoding

```python
from decoder import MeshCorePacketDecoder

hex_data = '11007E7662676F7F...'
packet = MeshCorePacketDecoder.decode_packet(hex_data)

print(packet['type'])  # "NODEINFO"
print(packet['text_strings'])  # ["WW7STR/PugetMesh Cougar"]
```

### With Structure Analysis

```python
packet = MeshCorePacketDecoder.decode_packet(hex_data, include_structure=True)

# Includes 'structure' field with detailed breakdown
print(packet['structure'])
```

## Testing

Run the test suite:

```bash
python3 test_decoder.py
python3 example_decode.py
```

## Comparison: Before vs After

### Before
- Basic packet type detection
- Minimal field extraction
- No routing analysis
- No text extraction
- Simple structure

### After
- Full packet structure analysis
- Routing information extraction
- Automatic text string extraction
- Varint and protobuf support
- Detailed structure breakdown
- Enhanced CLI options

## Output Example

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
  "strings": ["WW7STR/PugetMesh Cougar"],
  "text_strings": ["WW7STR/PugetMesh Cougar"],
  "node_num": 0
}
```

## Integration

The enhanced decoder is already integrated with:

- `mqttreader.py` - MQTT packet reading
- `decode_raw_packets.py` - Batch packet decoding
- `extract_nodes_from_packets.py` - Node information extraction

## See Also

- [DECODER_USAGE.md](DECODER_USAGE.md) - Full usage documentation
- [TypeScript meshcore-decoder](https://github.com/michaelhart/meshcore-decoder) - Reference implementation
