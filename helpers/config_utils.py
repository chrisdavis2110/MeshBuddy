"""
Configuration utilities for managing config.ini files.
"""

import configparser
import logging
import sys

logger = logging.getLogger(__name__)


def load_config(config_file="config.ini"):
    """
    Load configuration from config.ini file

    Args:
        config_file (str): Path to the configuration file

    Returns:
        configparser.ConfigParser: Loaded configuration object

    Raises:
        SystemExit: If configuration cannot be loaded
    """
    config = configparser.ConfigParser()
    try:
        config.read(config_file)
        logger.info("Configuration loaded successfully")
        return config
    except Exception as e:
        logger.error(f"Failed to load configuration: {str(e)}")
        sys.exit(1)
