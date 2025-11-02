#!/usr/bin/env python3
"""
Example usage of MeshCore Packet Decoder
Shows how to use the decoder to get TypeScript-compatible output
"""

from decoder import MeshCorePacketDecoder
import json

# Example packet from the meshcore-decoder TypeScript library
hex_data = '11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C94006CE7CF682E58408DD8FCC51906ECA98EBF94A037886BDADE7ECD09FD92B839491DF3809C9454F5286D1D3370AC31A34593D569E9A042A3B41FD331DFFB7E18599CE1E60992A076D50238C5B8F85757375354522F50756765744D65736820436F75676172'

# Decode the packet with detailed format matching TypeScript
decoded = MeshCorePacketDecoder.decode_detailed(hex_data)

if decoded:
    print("Decoded Packet:")
    print(json.dumps(decoded, indent=2))

    # Access specific fields
    print("\n" + "=" * 80)
    print("Extracted Information:")
    print("=" * 80)

    app_data = decoded['payload']['decoded'].get('appData', {})

    print(f"Device Name: {app_data.get('name', 'Unknown')}")
    print(f"Device Role: {app_data.get('deviceRole', 'Unknown')}")

    if app_data.get('hasLocation'):
        location = app_data.get('location', {})
        print(f"Location: {location.get('latitude')}, {location.get('longitude')}")

    print(f"Flags: {app_data.get('flags', 0)}")
    print(f"Has Name: {app_data.get('hasName', False)}")
    print(f"Has Location: {app_data.get('hasLocation', False)}")

    # Show header information
    print(f"\nPacket Header Info:")
    print(f"  Message Hash: {decoded['messageHash']}")
    print(f"  Payload Type: {decoded['payloadType']}")
    print(f"  Route Type: {decoded['routeType']}")
    print(f"  Total Bytes: {decoded['totalBytes']}")
else:
    print("Failed to decode packet")
