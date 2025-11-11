"""
Mesh-specific utilities for mesh network operations.
"""

import logging
import requests

logger = logging.getLogger(__name__)


def get_data_from_mqtt(mqtt_api_url):
    """
    Fetch data from MQTT API endpoint

    Args:
        mqtt_api_url (str): URL of the MQTT API endpoint

    Returns:
        dict: JSON data from the API, or None if failed
    """
    try:
        response = requests.get(mqtt_api_url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        logger.error(f"Error fetching data from MQTT API: {str(e)}")
        return None
