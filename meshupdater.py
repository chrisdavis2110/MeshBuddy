#!/usr/bin/python3

import os
import sys
from meshmqtt import MeshMQTTBridge

if __name__ == "__main__":
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Initialize bridge with absolute paths
    bridge = MeshMQTTBridge(
        config_file=os.path.join(script_dir, "config.ini"),
        data_dir=script_dir
    )

    # Run the update
    bridge.update_nodes_data()