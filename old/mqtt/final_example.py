#!/usr/bin/env python3
"""Final example showing the correct output format"""

from decoder import MeshCorePacketDecoder
import json

hex_data = '11007E7662676F7F0850A8A355BAAFBFC1EB7B4174C340442D7D7161C9474A2C94006CE7CF682E58408DD8FCC51906ECA98EBF94A037886BDADE7ECD09FD92B839491DF3809C9454F5286D1D3370AC31A34593D569E9A042A3B41FD331DFFB7E18599CE1E60992A076D50238C5B8F85757375354522F50756765744D65736820436F75676172'

print("MeshCore Packet Decoder - TypeScript Compatible Output")
print("=" * 80)

decoded = MeshCorePacketDecoder.decode_detailed(hex_data)

if decoded:
    print(json.dumps(decoded, indent=2))

    print("\n" + "=" * 80)
    print("Usage in your code:")
    print("=" * 80)
    print("""
from decoder import MeshCorePacketDecoder

# Decode with TypeScript-compatible format
hex_data = '11007E7662676F7F...'
decoded = MeshCorePacketDecoder.decode_detailed(hex_data)

# Access fields
print(decoded['payload']['decoded']['appData']['name'])
print(decoded['payload']['decoded']['appData']['location'])
    """)
else:
    print("Failed to decode")
