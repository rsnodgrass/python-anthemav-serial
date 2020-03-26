""" Read the configuration for supported devices """
import os
import yaml
import logging
import pprint as pp

LOG = logging.getLogger(__name__)

DEVICE_CONFIG = {}
PROTOCOL_CONFIG = {}

def _load_config(config_file):
    """Load the amp series configuration"""

#    LOG.debug(f"Loading {config_file}")
    with open(config_file, 'r') as stream:
        try:
            config = yaml.load(stream, Loader=yaml.FullLoader)
            return config[0]
        except yaml.YAMLError as exc:
            LOG.error(f"Failed reading config {config_file}: {exc}")
            return None

def _load_config_dir(directory):
    config_tree = {}

    for filename in os.listdir(directory):
        try:
          if filename.endswith('.yaml'):
                series = filename.split('.yaml')[0]
                config = _load_config(os.path.join(directory, filename))
                if config:
                    config_tree[series] = config
        except Exception as e:
            LOG.warning(f"Failed parsing {filename}; ignoring that configuratio file")

    return config_tree

def get_with_log(name, dictionary, key: str):
    value = dictionary.get(key)
    if value:
        return dictionary.get(key)
    LOG.warning(f"Invalid key '{key}' in dictionary '{name}'; returning None")
    return None

config_dir = os.path.dirname(__file__)
DEVICE_CONFIG = _load_config_dir(f"{config_dir}/series")
PROTOCOL_CONFIG = _load_config_dir(f"{config_dir}/protocols")