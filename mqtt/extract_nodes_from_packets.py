#!/usr/bin/env python3
"""
Extract node information from raw packets
Creates nodes.json-like output from decoded packet data
"""

import json
import struct
from typing import Dict, Any, Optional
from datetime import datetime


def extract_text_from_packet(packet_data: str) -> Optional[str]:
    """Try to extract text/name from packet data"""
    try:
        # Skip header and try to find ASCII text
        bytes_data = bytes.fromhex(packet_data)
        # Look for readable ASCII text (device names, etc.)
        text_parts = []
        current_text = ""

        for i in range(1, min(len(bytes_data), 200)):  # Check first 200 bytes
            b = bytes_data[i]
            if 32 <= b <= 126:  # Printable ASCII
                current_text += chr(b)
            else:
                if len(current_text) >= 3:  # Only keep substantial text
                    text_parts.append(current_text)
                current_text = ""

        if len(current_text) >= 3:
            text_parts.append(current_text)

        # Return the longest text found (likely device name)
        if text_parts:
            return max(text_parts, key=len)
    except:
        pass
    return None


def decode_protobuf_field(data: bytes, offset: int) -> tuple[Optional[str], int]:
    """Decode a protobuf varint field"""
    if offset >= len(data):
        return None, offset

    value = 0
    shift = 0
    i = offset

    while i < len(data):
        byte = data[i]
        value |= (byte & 0x7F) << shift
        shift += 7

        if (byte & 0x80) == 0:
            return chr(value) if value < 256 else None, i + 1
        i += 1

    return None, offset


def extract_name_from_nodeinfo(packet_hex: str) -> Optional[str]:
    """Extract device name from NODEINFO packet"""
    # Try to find ASCII strings in the packet
    # Names typically appear in specific positions
    try:
        # Method 1: Look for the last meaningful ASCII string
        text = extract_text_from_packet(packet_hex)
        if text:
            # Filter out common hex patterns
            if not text.isdigit() and len(text) > 1:
                return text

        # Method 2: Try to decode as protobuf strings
        packet_bytes = bytes.fromhex(packet_hex)

        # Skip header
        data = packet_bytes[1:]

        # Look for string fields (tag type 2)
        for i in range(min(200, len(data))):
            if i < len(data) - 1:
                # Check if this could be a string field
                tag = data[i]
                if tag & 0x07 == 2:  # Wire type 2 (string)
                    field_num = tag >> 3
                    if field_num >= 1 and field_num <= 10:  # Common field numbers
                        length = data[i + 1] if i + 1 < len(data) else 0
                        if length > 0 and length < 100:  # Reasonable string length
                            if i + 2 + length <= len(data):
                                try:
                                    string_data = data[i + 2:i + 2 + length]
                                    text = string_data.decode('utf-8', errors='ignore')
                                    if len(text) >= 2 and text.isprintable():
                                        return text
                                except:
                                    pass
    except Exception as e:
        pass

    return None


def determine_device_role(packet_hex: str) -> int:
    """Try to determine device role from packet"""

    # Priority 1: Check name for explicit device type keywords

    # Priority 2: Use packet characteristics as fallback
    packet_bytes = bytes.fromhex(packet_hex)

    # Very short packets are usually companions
    if len(packet_bytes) < 80:
        return 1  # Companion

    # Medium length might be companions or repeaters (default to companion)
    if len(packet_bytes) < 120:
        return 1  # Companion

    # Very long packets (>120 bytes) are likely repeaters
    return 2  # Likely repeater


def extract_node_id_from_packet(packet_hex: str) -> Optional[str]:
    """Extract the actual mesh node ID from the packet data"""
    try:
        # Packet structure: header + node number (varint) + data
        # After header byte, there's usually node information encoded
        packet_bytes = bytes.fromhex(packet_hex)

        if len(packet_bytes) < 5:
            return None

        # Skip header (first byte)
        data = packet_bytes[1:]

        # Try to find a 32-byte public key in the packet
        # Public keys are 32 bytes = 64 hex chars
        for i in range(len(data) - 31):
            # Check if we have enough bytes
            candidate = data[i:i+32]

            # Check if it looks like a valid public key
            # Valid hex and reasonable distribution
            if all(32 <= b <= 126 or b in range(0, 10) for b in candidate[:8]):
                # Try to decode as potential node number first
                pass

        return None
    except Exception as e:
        pass
    return None


def determine_device_role_from_name(name: str) -> int:
    """Determine device role from name"""
    if not name:
        return 1  # Default to Companion

    name_lower = name.lower()

    # Room Server detection
    if 'room server' in name_lower or 'roomserver' in name_lower:
        return 3

    # Repeater detection
    if 'repeater' in name_lower or 'rpt' in name_lower or 'rptr' in name_lower or 'wcmesh.com' in name_lower:
        return 2

    # Companion detection
    if 'pocket' in name_lower or 'mobile' in name_lower or 'deck' in name_lower or 'companion' in name_lower or 'lowmesh' in name_lower:
        return 1

    # Default to Companion
    return 1


def create_node_entry_from_mqtt_data(mqtt_node: dict, first_seen: str, last_seen: str, gateway_name: str = None) -> Dict[str, Any]:
    """Create a node entry from MQTT data"""

    public_key = mqtt_node.get('public_key')
    name = mqtt_node.get('name', f"Node_{public_key[:8]}")

    # Determine device role from name
    device_role = determine_device_role_from_name(name)

    # Determine mode and flags based on device role
    mode_map = {1: 'Companion', 2: 'Repeater', 3: 'Room Server'}
    flags_map = {1: 129, 2: 146, 3: 147}

    device_mode = mode_map.get(device_role, 'Companion')
    flags = flags_map.get(device_role, 129)

    # Get raw packet if available
    decoded_payload = mqtt_node.get('decoded_payload', {}).copy()

    # Update decoded payload with proper structure
    decoded_payload.update({
        'mode': device_mode,
        'name': name,
        'flags': flags,
        'timestamp': int(datetime.now().timestamp()),
        'public_key': public_key,
        'type': 'NODEINFO'
    })

    # Add gateway tracking
    if gateway_name:
        if 'gateways' in decoded_payload:
            if isinstance(decoded_payload['gateways'], list) and gateway_name not in decoded_payload['gateways']:
                decoded_payload['gateways'].append(gateway_name)
        else:
            decoded_payload['gateways'] = [gateway_name]

    # Create node entry
    node = {
        'public_key': public_key,
        'name': name,
        'device_role': device_role,
        'first_seen': first_seen,
        'last_seen': last_seen,
        'regions': mqtt_node.get('regions', ['LAX']),
        'is_mqtt_connected': mqtt_node.get('is_mqtt_connected', False),
        'decoded_payload': decoded_payload,
        'location': mqtt_node.get('location')
    }

    return node


def convert_mqtt_to_nodes(input_file: str, output_file: str):
    """Convert mqttnodes.json to nodes.json format"""

    with open(input_file, 'r') as f:
        data = json.load(f)

    # Get timestamp
    timestamp = data.get('timestamp', datetime.now().isoformat())

    # Convert each node, deduplicate by actual packet content
    nodes_dict = {}  # Use dict to deduplicate by actual node
    seen_packets = {}  # Track unique packet content

    for mqtt_node in data.get('data', []):
        decoded_payload = mqtt_node.get('decoded_payload', {})
        raw_packet = decoded_payload.get('raw')
        gateway_name = decoded_payload.get('origin', 'Unknown')

        if raw_packet:
            # Create a signature for this packet content (without node number part)
            # This helps deduplicate when same packet is seen by multiple gateways
            # Use the LAST part of the packet (payload) since gateways modify the routing info
            packet_signature = raw_packet[-100:]  # Last 100 hex chars = 50 bytes of payload

            # Use packet signature as key, but prefer the node_id from origin_id
            actual_node_id = decoded_payload.get('origin_id', mqtt_node.get('public_key'))

            # Get the name from the decoded_payload fields
            node_name = mqtt_node.get('name')

            # If we've seen this packet signature before, it's the same node seen by different gateway
            if packet_signature not in seen_packets:
                # First time seeing this packet - create node entry
                node = create_node_entry_from_mqtt_data(
                    mqtt_node,
                    first_seen=mqtt_node.get('first_seen', timestamp),
                    last_seen=mqtt_node.get('last_seen', timestamp),
                    gateway_name=gateway_name
                )

                # Track this packet signature
                seen_packets[packet_signature] = node['public_key']

                # Store in dict by actual node ID (not gateway ID)
                nodes_dict[node['public_key']] = node
            else:
                # This packet was seen before - it's a duplicate from different gateway
                # Just update the last_seen time
                existing_node_id = seen_packets[packet_signature]
                if existing_node_id in nodes_dict:
                    nodes_dict[existing_node_id]['last_seen'] = mqtt_node.get('last_seen', timestamp)
                    # Track which gateways have seen this
                    if 'gateways' not in nodes_dict[existing_node_id]['decoded_payload']:
                        nodes_dict[existing_node_id]['decoded_payload']['gateways'] = []
                    if gateway_name not in nodes_dict[existing_node_id]['decoded_payload']['gateways']:
                        nodes_dict[existing_node_id]['decoded_payload']['gateways'].append(gateway_name)
        else:
            # No raw packet, create basic entry
            actual_node_id = decoded_payload.get('origin_id', mqtt_node.get('public_key'))
            node = {
                'public_key': actual_node_id,
                'name': mqtt_node.get('name', f"Node_{actual_node_id[:8]}"),
                'device_role': mqtt_node.get('device_role', 1),
                'first_seen': mqtt_node.get('first_seen', timestamp),
                'last_seen': mqtt_node.get('last_seen', timestamp),
                'regions': mqtt_node.get('regions', ['LAX']),
                'is_mqtt_connected': mqtt_node.get('is_mqtt_connected', False),
                'decoded_payload': decoded_payload,
                'location': mqtt_node.get('location')
            }
            # Store in dict by actual node ID (deduplicates)
            nodes_dict[actual_node_id] = node

    # Convert dict to list and sort
    nodes_list = list(nodes_dict.values())
    nodes_list.sort(key=lambda x: x['public_key'])

    # Create output in nodes.json format
    output = {
        'timestamp': timestamp,
        'data': nodes_list
    }

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Converted {len(nodes_list)} nodes from {input_file}")
    print(f"Output saved to: {output_file}")


if __name__ == "__main__":
    import sys

    input_file = sys.argv[1] if len(sys.argv) > 1 else "mqttnodes.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "nodes_from_packets.json"

    convert_mqtt_to_nodes(input_file, output_file)
