#!/usr/bin/env python3
"""
MQTT Reader for MeshCore Network
Connects to MQTT broker and collects node data
"""

import json
import logging
import ssl
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, Optional

from decoder import MeshCorePacketDecoder

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("paho-mqtt is required. Install it with: pip install paho-mqtt")
    sys.exit(1)

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class MeshMQTTReader:
    def __init__(self, broker_host: str, broker_port: int, username: str = None, password: str = None):
        """
        Initialize MQTT reader

        Args:
            broker_host: MQTT broker hostname
            broker_port: MQTT broker port
            username: MQTT username (optional)
            password: MQTT password (optional)
        """
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password

        # Storage for collected data
        self.nodes = {}  # Store nodes by public_key (auto-deduplicates)
        self.last_seen = {}  # Track last seen timestamps
        self.save_counter = 0  # Counter for auto-save
        self.auto_save_interval = 10  # Save every N updates
        self.output_file = "mqttnodes.json"  # Output filename
        self.packet_signatures = {}  # Track unique packets by payload signature

        # Initialize MQTT client
        self.client = mqtt.Client(
            client_id=f"meshreader_{int(time.time())}",
            clean_session=True
        )

        # Set callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.client.on_subscribe = self.on_subscribe

        # Configure TLS
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)

        # Set username/password if provided
        if username and password:
            self.client.username_pw_set(username, password)

    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            logger.info(f"Connected to MQTT broker {self.broker_host}:{self.broker_port}")

            # Subscribe to packets topic only
            topics = [
                "meshcore/LAX/+/packets",
            ]

            for topic in topics:
                client.subscribe(topic, qos=1)
                logger.info(f"Subscribed to {topic}")
        else:
            logger.error(f"Failed to connect with code {rc}")

    def on_message(self, client, userdata, msg):
        """Callback when message is received"""
        try:
            topic_parts = msg.topic.split('/')

            # Log every message received
            logger.info(f"Received message on topic: {msg.topic}")

            # Try to parse as JSON
            try:
                data = json.loads(msg.payload.decode('utf-8'))
                logger.debug(f"Parsed JSON data: {json.dumps(data, indent=2)}")
                self.process_json_message(topic_parts, data)
            except json.JSONDecodeError:
                # Binary packet - might need decoding
                logger.debug(f"Binary packet received, length: {len(msg.payload)}")
                self.process_binary_packet(msg.topic, msg.payload)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def process_json_message(self, topic_parts: list, data: dict):
        """Process JSON message"""
        # Try to extract node ID from topic
        node_id = None
        for i, part in enumerate(topic_parts):
            if part and len(part) == 64:  # Public key length
                node_id = part
                break

        # Add node_id to data if found in topic but not in data
        if node_id and 'id' not in data and 'node_id' not in data:
            data['id'] = node_id

        # Handle the message
        self.handle_node_data(data, topic_parts)

    def process_binary_packet(self, topic: str, payload: bytes):
        """Process binary packet"""
        try:
            # Use the decoder to parse the packet
            parsed = MeshCorePacketDecoder.parse_mqtt_message(topic, payload)

            if parsed and 'public_key' in parsed:
                node_id = parsed['public_key']

                # Update or create node entry
                if node_id not in self.nodes:
                    self.nodes[node_id] = {
                        'public_key': node_id,
                        'name': parsed.get('name', f"Node_{node_id[:8]}"),
                        'device_role': 1 if parsed.get('mode') != 'Repeater' else 2,
                        'first_seen': datetime.now().isoformat(),
                        'regions': ['LAX'],
                        'is_mqtt_connected': True,
                        'decoded_payload': parsed,
                        'location': None
                    }

                self.nodes[node_id]['last_seen'] = datetime.now().isoformat()
                self.last_seen[node_id] = datetime.now()

                # Auto-save after collecting data
                self.save_counter += 1
                if self.save_counter >= self.auto_save_interval:
                    self.auto_save()
                    self.save_counter = 0

                logger.debug(f"Updated node from binary packet: {node_id[:16]}")

        except Exception as e:
            logger.error(f"Error processing binary packet: {e}")

    def handle_nodeinfo(self, data: dict):
        """Handle nodeinfo message"""
        # Try to extract node ID from various possible locations
        node_id = data.get('id') or data.get('node_id') or data.get('from')

        if node_id:
            # Extract name from various possible locations
            name = None
            if 'user' in data:
                if isinstance(data['user'], dict):
                    name = data['user'].get('longname') or data['user'].get('shortname')
                else:
                    name = data['user']
            else:
                name = data.get('name') or data.get('longname') or data.get('shortname')

            if not name:
                name = f"Node_{node_id[:8]}"

            # Create or update node entry
            if node_id not in self.nodes:
                self.nodes[node_id] = {
                    'public_key': node_id,
                    'name': name,
                    'device_role': data.get('device_role', 1),
                    'first_seen': datetime.now().isoformat(),
                    'last_seen': datetime.now().isoformat(),
                    'regions': data.get('regions', ['LAX']),
                    'is_mqtt_connected': True,
                    'decoded_payload': data.copy()
                }
            else:
                # Update existing node
                self.nodes[node_id]['name'] = name
                if 'device_role' in data:
                    self.nodes[node_id]['device_role'] = data['device_role']
                self.nodes[node_id]['decoded_payload'].update(data)

            self.nodes[node_id]['last_seen'] = datetime.now().isoformat()
            self.last_seen[node_id] = datetime.now()

            # Auto-save after collecting data
            self.save_counter += 1
            if self.save_counter >= self.auto_save_interval:
                self.auto_save()
                self.save_counter = 0

            logger.info(f"Updated node: {name} ({node_id[:16]}...)")

    def handle_node_data(self, data: dict, topic_parts: list = None):
        """Handle node data/position updates"""
        # Get the originating node ID (not the gateway ID)
        # The 'origin_id' in decoded_payload tells us which node sent the packet
        node_id = data.get('decoded_payload', {}).get('origin_id')

        # Fallback to topic or direct ID
        if not node_id:
            node_id = data.get('from') or data.get('id')

        if node_id:
            # Extract gateway info for metadata
            gateway_info = {
                'origin': data.get('decoded_payload', {}).get('origin', 'Unknown'),
                'received_via': data.get('decoded_payload', {}).get('id')  # The gateway's ID
            }

            # Decode raw packet if present and extract node info
            device_name = None
            device_mode = 'Companion'
            lat = None
            lon = None

            if 'raw' in data:
                raw_packet = data['raw']
                decoded = MeshCorePacketDecoder.decode_packet(raw_packet)
                if decoded:
                    data['decoded'] = decoded

                    # Create packet signature from payload (skip routing info)
                    # Use last 100 hex chars (50 bytes) as signature since gateways only modify routing
                    packet_signature = raw_packet[-100:] if len(raw_packet) > 100 else raw_packet

                    # Check if we've seen this packet before from a different gateway
                    if packet_signature in self.packet_signatures:
                        # Duplicate packet from different gateway
                        existing_node_id = self.packet_signatures[packet_signature]
                        logger.debug(f"Skipping duplicate packet from {gateway_info.get('origin')} (already seen)")

                        # Just update last_seen and add gateway to tracking
                        if existing_node_id in self.nodes:
                            self.nodes[existing_node_id]['last_seen'] = datetime.now().isoformat()
                            self.last_seen[existing_node_id] = datetime.now()

                            if 'gateways' not in self.nodes[existing_node_id]['decoded_payload']:
                                self.nodes[existing_node_id]['decoded_payload']['gateways'] = []
                            if gateway_info.get('origin') not in self.nodes[existing_node_id]['decoded_payload']['gateways']:
                                self.nodes[existing_node_id]['decoded_payload']['gateways'].append(gateway_info.get('origin'))

                        return  # Skip processing this duplicate

                    # Record this as new packet
                    self.packet_signatures[packet_signature] = node_id

                    # Determine mode from packet type and size
                    if decoded.get('type') == 'POSITION' and 'lat' in decoded:
                        device_mode = 'Repeater'
                        lat = decoded.get('lat')
                        lon = decoded.get('lon')
                    elif decoded.get('type_id') == 1:  # NODEINFO
                        # Determine mode from packet characteristics
                        # Use packet size and type heuristics
                        if len(raw_packet) > 200:
                            device_mode = 'Repeater'
                        else:
                            device_mode = 'Companion'

            # Get device name from MQTT data
            device_name = data.get('name') or data.get('longname') or f"Node_{node_id[:8]}"

            # Check name for device type hints
            if device_name:
                name_lower = device_name.lower()
                if 'room server' in name_lower or 'roomserver' in name_lower:
                    device_mode = 'Room Server'
                elif 'repeater' in name_lower or 'rpt' in name_lower or 'rptr' in name_lower or 'wcmesh.com' in name_lower or 'wcmesh' in name_lower:
                    device_mode = 'Repeater'
                elif 'pocket' in name_lower or 'mobile' in name_lower or 'deck' in name_lower or 'companion' in name_lower or 'lowmesh' in name_lower:
                    device_mode = 'Companion'

            if node_id not in self.nodes:
                # Determine device role from mode
                role_map = {'Companion': 1, 'Repeater': 2, 'Room Server': 3}
                device_role = role_map.get(device_mode, 1)

                # Determine flags from device role
                flags_map = {1: 129, 2: 146, 3: 147}
                flags = flags_map.get(device_role, 129)

                # New node - create entry
                self.nodes[node_id] = {
                    'public_key': node_id,
                    'name': device_name,
                    'device_role': device_role,
                    'first_seen': datetime.now().isoformat(),
                    'last_seen': datetime.now().isoformat(),
                    'regions': data.get('regions', ['LAX']),
                    'is_mqtt_connected': True,
                    'decoded_payload': {
                        'mode': device_mode,
                        'name': device_name,
                        'flags': flags,
                        'timestamp': int(datetime.now().timestamp()),
                        'public_key': node_id,
                        'raw': data.get('raw'),  # Store raw packet from first sighting
                        'gateways': [gateway_info]  # Track which gateways saw this
                    },
                    'location': None
                }

                # Add location if available
                if lat and lon:
                    self.nodes[node_id]['location'] = {
                        'latitude': lat,
                        'longitude': lon
                    }
                    self.nodes[node_id]['decoded_payload'].update({
                        'lat': lat,
                        'lon': lon
                    })
            else:
                # Existing node - update last_seen and track gateway
                self.nodes[node_id]['last_seen'] = datetime.now().isoformat()
                self.last_seen[node_id] = datetime.now()

                # Update gateway tracking
                if 'gateways' in self.nodes[node_id]['decoded_payload']:
                    if gateway_info.get('origin') not in self.nodes[node_id]['decoded_payload']['gateways']:
                        self.nodes[node_id]['decoded_payload']['gateways'].append(gateway_info.get('origin'))
                        logger.debug(f"Added gateway {gateway_info.get('origin')} for node {node_id[:16]}")

                logger.debug(f"Updated last_seen for {node_id} (already exists)")

                # Auto-save after collecting data
                self.save_counter += 1
                if self.save_counter >= self.auto_save_interval:
                    self.auto_save()
                    self.save_counter = 0

                return  # Done processing this message

            # Update fields
            if 'latitude' in data and 'longitude' in data:
                self.nodes[node_id]['location'] = {
                    'latitude': data['latitude'],
                    'longitude': data['longitude']
                }
                self.nodes[node_id]['decoded_payload'].update({
                    'lat': data['latitude'],
                    'lon': data['longitude']
                })

            # Update last seen
            self.nodes[node_id]['last_seen'] = datetime.now().isoformat()
            self.last_seen[node_id] = datetime.now()

            # Auto-save after collecting data
            self.save_counter += 1
            if self.save_counter >= self.auto_save_interval:
                self.auto_save()
                self.save_counter = 0

    def on_subscribe(self, client, userdata, mid, granted_qos):
        """Callback when subscribe is successful"""
        logger.info(f"Subscribed to topics with QoS: {granted_qos}")

    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        if rc != 0:
            logger.warning(f"Unexpected disconnect (code: {rc})")
        else:
            logger.info("Disconnected from MQTT broker")

    def connect(self):
        """Connect to MQTT broker"""
        try:
            logger.info(f"Connecting to MQTT broker {self.broker_host}:{self.broker_port}")
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            return True
        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            return False

    def start(self):
        """Start the MQTT client (non-blocking)"""
        self.client.loop_start()

    def stop(self):
        """Stop the MQTT client"""
        logger.info("Stopping MQTT client...")
        self.client.loop_stop()
        self.client.disconnect()

    def auto_save(self):
        """Auto-save data to file"""
        nodes_list = []
        for node_id, node_data in self.nodes.items():
            # Update last_seen if available
            if node_id in self.last_seen:
                node_data['last_seen'] = self.last_seen[node_id].isoformat()

            nodes_list.append(node_data)

        # Sort by public_key
        nodes_list.sort(key=lambda x: x['public_key'])

        output = {
            'timestamp': datetime.now().isoformat(),
            'data': nodes_list
        }

        try:
            with open(self.output_file, 'w') as f:
                json.dump(output, f, indent=2)
            logger.info(f"Auto-saved {len(nodes_list)} nodes to {self.output_file}")
        except Exception as e:
            logger.error(f"Error auto-saving: {e}")

    def collect_data_continuous(self):
        """
        Collect data continuously until interrupted
        """
        logger.info(f"Starting continuous data collection...")
        logger.info(f"Auto-save interval: every {self.auto_save_interval} updates")
        logger.info(f"Press Ctrl+C to stop and save")

        try:
            # Keep running indefinitely
            while True:
                time.sleep(60)  # Wake up every minute to log status
                logger.info(f"Status: {len(self.nodes)} nodes collected")
        except KeyboardInterrupt:
            logger.info("\nStopping continuous collection...")

    def save_to_json(self, filename: str = "mqttnodes.json"):
        """Save collected data to JSON file"""
        nodes_list = []
        for node_id, node_data in self.nodes.items():
            # Update last_seen if available
            if node_id in self.last_seen:
                node_data['last_seen'] = self.last_seen[node_id].isoformat()

            nodes_list.append(node_data)

        # Sort by public_key
        nodes_list.sort(key=lambda x: x['public_key'])

        output = {
            'timestamp': datetime.now().isoformat(),
            'data': nodes_list
        }

        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"Saved {len(nodes_list)} nodes to {filename}")
        return output


def main():
    """Main function"""
    # MQTT broker configuration
    BROKER_HOST = "mqtt.wcmesh.com"
    BROKER_PORT = 8883
    USERNAME = "wcmesh"
    PASSWORD = "meshcoast"

    # Get credentials from user or environment
    import argparse
    parser = argparse.ArgumentParser(description='MQTT Reader for MeshCore Network')
    parser.add_argument('--username', type=str, help='MQTT username')
    parser.add_argument('--password', type=str, help='MQTT password')
    parser.add_argument('--duration', type=int, default=-1, help='Collection duration in seconds (-1 for continuous)')
    parser.add_argument('--output', type=str, default='mqttnodes.json', help='Output filename')
    parser.add_argument('--save-interval', type=int, default=10, help='Auto-save every N updates')

    args = parser.parse_args()

    # Create reader
    reader = MeshMQTTReader(
        broker_host=BROKER_HOST,
        broker_port=BROKER_PORT,
        username=USERNAME,
        password=PASSWORD
    )

    # Set auto-save interval
    reader.auto_save_interval = args.save_interval

    # Set output file
    reader.output_file = args.output

    try:
        # Connect and start
        if not reader.connect():
            logger.error("Failed to connect to MQTT broker")
            return

        reader.start()

        # Collect data for specified duration or continuously
        if args.duration > 0:
            logger.info(f"Collecting data for {args.duration} seconds...")
            time.sleep(args.duration)
            logger.info(f"Finished collecting data. Found {len(reader.nodes)} nodes.")

            # Final save
            reader.save_to_json(args.output)

            logger.info(f"\nSummary:")
            logger.info(f"Nodes found: {len(reader.nodes)}")
            logger.info(f"Output file: {args.output}")
        else:
            # Continuous mode
            reader.collect_data_continuous()

            # Final save on exit
            reader.save_to_json(args.output)
            logger.info(f"\nFinal summary:")
            logger.info(f"Nodes found: {len(reader.nodes)}")
            logger.info(f"Output file: {args.output}")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        # Final save on interruption
        reader.auto_save()
    finally:
        reader.stop()


if __name__ == "__main__":
    main()
