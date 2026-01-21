#!/usr/bin/env python3
"""
MQTT Subscriber - Receives data from MQTT broker and creates node files
"""

import paho.mqtt.client as mqtt
import json
import logging
import configparser
import time
import requests
from datetime import datetime
from typing import Optional

from meshcoredecoder import MeshCoreDecoder
from meshcoredecoder.utils.enum_names import get_payload_type_name

# Import NodeDataProcessor from nodes.py
from mqtt.nodes import NodeDataProcessor


class MQTTSubscriber:
    def __init__(self, config_file="config.ini"):
        """Initialize MQTT subscriber with configuration"""
        self.client = None  # Initialize client attribute early
        self._cleanup_done = False  # Track if cleanup has been called
        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        # Get MQTT settings from config (with fallback to empty if not configured)
        self.broker_url = self.config.get("mqtt", "mqtt_url", fallback="")
        self.broker_port = self.config.getint("mqtt", "mqtt_port", fallback=443)
        self.username = self.config.get("mqtt", "mqtt_username", fallback="")
        self.password = self.config.get("mqtt", "mqtt_password", fallback="")

        # Check if MQTT is configured
        self.use_mqtt = bool(self.broker_url and self.broker_url.strip())

        # Get transport type (tcp or websockets)
        transport_type = self.config.get("mqtt", "mqtt_transport", fallback="tcp")
        if transport_type == "websockets":
            self.transport = "websockets"
        else:
            self.transport = "tcp"

        # Get WebSocket path if using websockets
        self.ws_path = self.config.get("mqtt", "mqtt_ws_path", fallback="/")

        # Get TLS setting
        self.use_tls = self.config.getboolean("mqtt", "mqtt_tls", fallback=True)

        # Topics to subscribe to
        topics_string = self.config.get("mqtt", "mqtt_topics")
        self.topics = [topic.strip() for topic in topics_string.split(',')]

        # Load region to log name mappings (for node file names)
        self.region_log_map = {}
        if self.config.has_section("region_logs"):
            for region, log_name in self.config.items("region_logs"):
                self.region_log_map[region.upper()] = log_name.lower()

        # Set up logging
        self.setup_logging()

        # Log region mappings after logger is set up
        if self.region_log_map:
            self.logger.info(f"Loaded region mappings: {self.region_log_map}")

        # Initialize NodeDataProcessor instances per region
        self.region_processors = {}

        # Get API URL if available (used as backup if MQTT is not available)
        self.api_url = None
        if self.config.has_option("api", "api_url"):
            self.api_url = self.config.get("api", "api_url")

        # API polling interval (in seconds) - only used when MQTT is not available
        self.api_poll_interval = self.config.getint("api", "api_poll_interval", fallback=900)  # Default 15 minutes

        # Initialize processors for each region
        for region, log_name in self.region_log_map.items():
            output_file = f"nodes_{log_name}.json" if log_name != "data_log" else "nodes.json"
            processor = NodeDataProcessor(log_file=None, api_url=self.api_url, output_file=output_file)
            # Load existing nodes to preserve first_seen
            processor._load_existing_nodes()
            # Create empty file if it doesn't exist
            processor.create_empty_nodes_file()
            self.region_processors[log_name] = processor

        # Also create a default processor for unmapped regions
        default_processor = NodeDataProcessor(log_file=None, api_url=self.api_url, output_file="nodes.json")
        default_processor._load_existing_nodes()
        # Create empty file if it doesn't exist
        default_processor.create_empty_nodes_file()
        self.default_processor = default_processor

        # Only set up MQTT client if MQTT is configured
        if self.use_mqtt:
            self._setup_mqtt_client()
        else:
            self.client = None
            self.logger.info("MQTT not configured, will use API as backup")

    def _setup_mqtt_client(self):
        """Set up MQTT client (only called if MQTT is configured)"""
        # Set up MQTT client (using callback API version 2)
        try:
            # paho-mqtt 2.x uses CallbackAPIVersion
            if self.transport == "websockets":
                try:
                    # Try with websocket_path parameter (newer versions)
                    self.client = mqtt.Client(
                        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        transport=self.transport,
                        websocket_path=self.ws_path
                    )
                except TypeError:
                    # Fallback: create client and set websocket options separately
                    self.client = mqtt.Client(
                        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        transport=self.transport
                    )
                    if hasattr(self.client, 'ws_set_options'):
                        self.client.ws_set_options(path=self.ws_path)
            else:
                self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            # Fallback for older versions
            if self.transport == "websockets":
                self.client = mqtt.Client(transport=self.transport)
                if hasattr(self.client, 'ws_set_options'):
                    self.client.ws_set_options(path=self.ws_path)
            else:
                self.client = mqtt.Client()

        # CRITICAL: Initialize _sock attribute immediately after client creation
        # This prevents AttributeError in paho-mqtt's __del__ method
        # The __del__ method checks "if not self._sock:" which fails if _sock doesn't exist
        # Use multiple methods to ensure the attribute is always set
        try:
            # Method 1: Try normal assignment
            if not hasattr(self.client, '_sock'):
                self.client._sock = None
        except Exception:
            try:
                # Method 2: Use object.__setattr__ to bypass custom __setattr__
                object.__setattr__(self.client, '_sock', None)
            except Exception:
                try:
                    # Method 3: Use setattr as last resort
                    setattr(self.client, '_sock', None)
                except Exception:
                    pass  # If all methods fail, continue anyway

        # Also monkey-patch _sock_close to handle missing _sock gracefully
        # Store reference to client for closure
        client_ref = self.client
        try:
            if hasattr(client_ref, '_sock_close'):
                original_sock_close = client_ref._sock_close
                def safe_sock_close(client=client_ref):
                    try:
                        # Ensure _sock exists before calling original
                        if not hasattr(client, '_sock'):
                            try:
                                object.__setattr__(client, '_sock', None)
                            except Exception:
                                try:
                                    setattr(client, '_sock', None)
                                except Exception:
                                    pass
                        return original_sock_close()
                    except AttributeError:
                        # If _sock still doesn't exist, ensure it's set and return
                        try:
                            object.__setattr__(client, '_sock', None)
                        except Exception:
                            try:
                                setattr(client, '_sock', None)
                            except Exception:
                                pass
                        return
                # Bind the method properly
                import types
                client_ref._sock_close = types.MethodType(safe_sock_close, client_ref)
        except Exception:
            pass  # If monkey-patch fails, continue anyway

        self.client.username_pw_set(self.username, self.password)

        # Set up TLS if enabled
        if self.use_tls:
            self.client.tls_set(cert_reqs=mqtt.ssl.CERT_NONE)
            self.client.tls_insecure_set(True)

        # Set up callbacks
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.logger.info(f"Initialized MQTT subscriber for broker: {self.broker_url}:{self.broker_port} (transport: {self.transport}, TLS: {self.use_tls})")

    def cleanup(self):
        """Clean up MQTT client resources"""
        if self._cleanup_done:
            return  # Already cleaned up

        if self.client:
            try:
                if hasattr(self.client, 'loop_stop'):
                    self.client.loop_stop()
                if hasattr(self.client, 'disconnect'):
                    self.client.disconnect()
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.debug(f"Error during client cleanup: {e}")
            finally:
                # Always ensure _sock is set to prevent AttributeError in paho-mqtt's __del__
                try:
                    if not hasattr(self.client, '_sock'):
                        self.client._sock = None
                    # Also set _sock_close to prevent other potential issues
                    if not hasattr(self.client, '_sock_close'):
                        # Create a no-op method if needed
                        pass
                except Exception:
                    pass  # Ignore errors when setting _sock

        self._cleanup_done = True

    def setup_logging(self):
        """Set up logging to console"""
        # Create logger
        self.logger = logging.getLogger("mqtt_subscriber")
        self.logger.setLevel(logging.INFO)

        # Only add handler if it doesn't already exist (avoid duplicates)
        if not self.logger.handlers:
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

        # Prevent propagation to root logger to avoid duplicate messages
        self.logger.propagate = False

    def format_timestamp(self, ts_str: str) -> str:
        """Format timestamp string for display"""
        try:
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return ts_str

    def extract_origin_name(self, origin: str) -> str:
        """Extract just the name from origin, removing ' MQTT' suffix and extra whitespace"""
        if not origin:
            return 'unknown'
        # Remove ' MQTT' suffix if present
        name = origin
        return name

    def process_packet_data(self, data: dict, timestamp: str, region: Optional[str] = None) -> Optional[dict]:
        """Process packet data and return formatted info for logging"""
        try:
            # Only process PACKET entries with raw hex
            if data.get('type') != 'PACKET' or not data.get('raw'):
                return None

            raw_hex = data.get('raw', '')
            direction = data.get('direction', 'unknown')
            origin = data.get('origin', 'unknown')
            packet_type_raw = data.get('packet_type', '')

            # Decode the packet
            try:
                packet = MeshCoreDecoder.decode(raw_hex)
            except Exception as e:
                return {
                    'timestamp': timestamp,
                    'direction': direction,
                    'origin': origin,
                    'packet_type': 'decode_error',
                    'raw_packet_type': packet_type_raw,
                    'raw_hex': raw_hex,
                    'region': region,
                    'error': str(e)
                }

            # Get payload type name
            payload_type_name = get_payload_type_name(packet.payload_type) if packet.is_valid else 'Invalid'

            return {
                'timestamp': timestamp,
                'direction': direction,
                'origin': origin,
                'packet_type': payload_type_name,
                'raw_packet_type': packet_type_raw,
                'raw_hex': raw_hex,
                'region': region,
                'is_valid': packet.is_valid
            }
        except Exception as e:
            return {
                'timestamp': timestamp,
                'direction': 'error',
                'origin': 'error',
                'packet_type': 'error',
                'raw_packet_type': '',
                'raw_hex': data.get('raw', ''),
                'region': region,
                'error': str(e)
            }

    def format_packet_output(self, info: dict) -> str:
        """Format packet information for display (matching watch_packets.py format)"""
        direction = info['direction'].upper()
        origin = self.extract_origin_name(info.get('origin', 'unknown'))
        packet_type = info['packet_type']
        raw_hex = info.get('raw_hex', '')
        region = info.get('region', '')

        # Build output line
        parts = [
            direction,
            packet_type,
        ]

        # Add region code if available
        if region:
            parts.append(f"[{region}]")

        parts.append(origin)

        if raw_hex:
            parts.append(f"raw={raw_hex}")

        return " ".join(parts)


    def _extract_region_from_topic(self, topic):
        """Extract region code from topic (e.g., meshcore/OXR/+/packets -> OXR)"""
        parts = topic.split('/')
        if len(parts) >= 2 and parts[0] == "meshcore":
            return parts[1].upper()
        return None

    def _get_log_name_for_region(self, region):
        """Get the log file name for a given region"""
        if region and region in self.region_log_map:
            return self.region_log_map[region]
        elif region:
            return region.lower()
        else:
            return "data_log"  # Default fallback


    def process_packet_to_nodes(self, topic, data, timestamp, region):
        """Process packet directly to node files using NodeDataProcessor"""
        try:
            # Only process PACKET entries with raw hex (advertisement packets)
            # NodeDataProcessor.process_packet expects entries with topic ending in /packets
            if not topic.endswith('/packets'):
                return

            if data.get('type') != 'PACKET' or data.get('packet_type') != '4':
                return

            raw_hex = data.get('raw', '')
            if not raw_hex:
                return

            # Get the appropriate processor for this region
            log_name = self._get_log_name_for_region(region)
            if log_name in self.region_processors:
                processor = self.region_processors[log_name]
            else:
                processor = self.default_processor

            # Create a log entry structure that NodeDataProcessor expects
            # (mimicking what would be in a log file)
            log_entry = {
                "timestamp": timestamp,
                "topic": topic,
                "data": data
            }

            # Process the packet using NodeDataProcessor's process_packet method
            # This will decode and store the node
            processor.process_packet(log_entry)

            # Save nodes periodically (every 10 packets to avoid too frequent writes)
            # We'll use a simple counter per processor
            if not hasattr(processor, '_packet_count'):
                processor._packet_count = 0
            processor._packet_count += 1

            if processor._packet_count >= 10:
                processor.save_nodes_json()
                processor._packet_count = 0

        except Exception as e:
            self.logger.error(f"Error processing packet to nodes: {e}")

    def on_connect(self, client, userdata, flags, rc, *args):
        """Callback for when client connects to broker"""
        # Handle both API versions: VERSION1 uses int rc, VERSION2 uses ReasonCode object
        if hasattr(rc, 'value'):
            # VERSION2 API - rc is a ReasonCode object
            reason_code = rc.value
        else:
            # VERSION1 API - rc is an int
            reason_code = rc

        if reason_code == 0:
            self.logger.info("Successfully connected to MQTT broker")
            # Subscribe to all topics
            for topic in self.topics:
                client.subscribe(topic)
                self.logger.info(f"Subscribed to topic: {topic}")
        else:
            self.logger.error(f"Failed to connect to broker, return code {reason_code}")

    def on_message(self, client, userdata, msg):
        """Callback for when a message is received"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')

        # Extract region from topic
        region = self._extract_region_from_topic(topic)

        # Parse JSON if possible
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw_data": payload}

        # Process packet directly to node files (no logging of packet data)
        timestamp = datetime.now().isoformat()
        self.process_packet_to_nodes(topic, data, timestamp, region)

    def on_disconnect(self, client, userdata, rc, *args):
        """Callback for when client disconnects from broker"""
        # Handle both API versions: VERSION1 uses int rc, VERSION2 uses ReasonCode object
        if hasattr(rc, 'value'):
            # VERSION2 API - rc is a ReasonCode object
            reason_code = rc.value
        else:
            # VERSION1 API - rc is an int
            reason_code = rc

        if reason_code != 0:
            self.logger.warning(f"Unexpected disconnection from broker (rc={reason_code})")
        else:
            self.logger.info("Disconnected from broker")

    def fetch_from_api(self):
        """Fetch node data from API and update all processors"""
        if not self.api_url:
            self.logger.warning("No API URL configured for fallback")
            return False

        try:
            self.logger.info(f"Fetching node data from API: {self.api_url}")
            response = requests.get(self.api_url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'data' in data:
                    nodes = data['data']
                    self.logger.info(f"Fetched {len(nodes)} nodes from API")

                    # Update all processors with API data
                    for processor in self.region_processors.values():
                        processor._update_from_api_data(nodes)
                    self.default_processor._update_from_api_data(nodes)

                    # Save all node files
                    for processor in self.region_processors.values():
                        try:
                            processor.save_nodes_json()
                        except Exception as e:
                            self.logger.error(f"Error saving nodes file: {e}")
                    try:
                        self.default_processor.save_nodes_json()
                    except Exception as e:
                        self.logger.error(f"Error saving default nodes file: {e}")

                    return True
            else:
                self.logger.warning(f"API returned status code {response.status_code}")
                return False
        except Exception as e:
            self.logger.error(f"Error fetching from API: {e}")
            return False

    def start_api_polling(self):
        """Start API polling mode (used when MQTT is not available)"""
        self.logger.info("Starting API polling mode...")
        self.logger.info(f"Polling API every {self.api_poll_interval} seconds")
        self.logger.info("Press Ctrl+C to stop")

        try:
            # Initial fetch
            self.fetch_from_api()

            # Poll periodically
            while True:
                time.sleep(self.api_poll_interval)
                self.fetch_from_api()
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
            self.logger.info("API polling stopped")

    def start(self):
        """Start the MQTT subscriber (or API polling if MQTT is not available)"""
        if not self.use_mqtt:
            # Use API as backup
            self.start_api_polling()
            return

        # Try MQTT first
        try:
            self.logger.info(f"Connecting to MQTT broker at {self.broker_url}:{self.broker_port}")
            self.client.connect(self.broker_url, self.broker_port, 60)

            # Start the loop to process callbacks
            self.logger.info("Starting MQTT subscriber loop...")
            self.logger.info("Press Ctrl+C to stop")
            self.client.loop_forever()

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
            self.cleanup()

            # Save all node files before shutting down
            self._save_all_nodes()
            self.logger.info("MQTT subscriber stopped")
        except Exception as e:
            self.logger.error(f"Error connecting to MQTT broker: {e}")

            # Clean up client properly before falling back
            self.cleanup()

            self.logger.info("Falling back to API polling mode...")

            # Fall back to API polling
            if self.api_url:
                self.start_api_polling()
            else:
                self.logger.error("No API URL configured for fallback. Exiting.")
                raise

    def _save_all_nodes(self):
        """Save all node files"""
        self.logger.info("Saving node files...")
        for processor in self.region_processors.values():
            try:
                processor.save_nodes_json()
            except Exception as e:
                self.logger.error(f"Error saving nodes file: {e}")
        try:
            self.default_processor.save_nodes_json()
        except Exception as e:
            self.logger.error(f"Error saving default nodes file: {e}")

    def __del__(self):
        """Ensure cleanup happens on garbage collection"""
        if not self._cleanup_done:
            try:
                self.cleanup()
            except Exception:
                pass  # Ignore errors during garbage collection


def main():
    """Main entry point"""
    subscriber = MQTTSubscriber()
    subscriber.start()


if __name__ == "__main__":
    main()
