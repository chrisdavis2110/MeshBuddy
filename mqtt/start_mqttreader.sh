#!/bin/bash
# Script to run MQTT reader in the background

# Start the MQTT reader in background
nohup python mqttreader.py > mqttreader.log 2>&1 &

echo "MQTT Reader started in background"
echo "PID: $!"
echo "Log file: mqttreader.log"
echo ""
echo "To stop: kill $!"
echo "To view logs: tail -f mqttreader.log"
