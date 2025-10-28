#!/usr/bin/env python3
"""
Script to decode raw packets from mqttnodes.json
Usage: python decode_raw_packets.py [mqttnodes.json]
"""

import json
import sys
from decoder import MeshCorePacketDecoder

def decode_raw_packets(filename="mqttnodes.json"):
    """Decode all raw packets in the nodes JSON file"""

    # Load the JSON file
    with open(filename, 'r') as f:
        data = json.load(f)

    # Process each node
    for node in data.get('data', []):
        decoded_payload = node.get('decoded_payload', {})
        raw_packet = decoded_payload.get('raw')

        if raw_packet:
            print(f"\nNode: {node.get('name')}")
            print(f"Public Key: {node.get('public_key')}")
            print(f"Raw Packet: {raw_packet}")

            # Decode the packet
            decoded = MeshCorePacketDecoder.decode_packet(raw_packet)

            if decoded:
                print("\nDecoded Packet:")
                print(json.dumps(decoded, indent=2))

                # Update the node with decoded data
                if 'decoded' not in decoded_payload:
                    decoded_payload['decoded'] = decoded

                # Extract useful info
                if 'lat' in decoded and 'lon' in decoded:
                    node['location'] = {
                        'latitude': decoded['lat'],
                        'longitude': decoded['lon']
                    }
                    print(f"Location: {decoded['lat']}, {decoded['lon']}")

    # Save updated data
    output_file = filename.replace('.json', '_decoded.json')
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nDecoded data saved to: {output_file}")

if __name__ == "__main__":
    filename = sys.argv[1] if len(sys.argv) > 1 else "mqttnodes.json"
    decode_raw_packets(filename)
