import logging

import re
import time

import asyncio

from functools import wraps
from threading import RLock

from .const import MUTE_KEY, VOLUME_KEY, POWER_KEY, SOURCE_KEY, ZONE_KEY
from .config import DEVICE_CONFIG, PROTOCOL_CONFIG, RS232_RESPONSE_PATTERNS, pattern_to_dictionary, get_with_log
from .protocol_sync import get_sync_rs232_protocol
from .protocol_async import get_async_rs232_protocol

# FIXME:
# The Anthem has the ability to set a "transmit" status on its RS232 port, which, acc'd the documentation, 
# causes the unit to send ASCII data out any time it's state is changes, either by manual adjustment of the
# front panel or by the transmission of RS232 commands.
#
# - should we limit MAX volume by default; and have a way to disable 'safety'?
#   could be an issue with damaging speakers

LOG = logging.getLogger(__name__)

# FIXME: range or explicit volume values should be configered per amp series in yaml
MAX_VOLUME = 100

class AmpControlBase(object):
    """
    AmpliferControlBase amplifier interface
    """

    def is_connected(self):
        """
        Returns True if the amplifier is connected and responding
        """
        raise NotImplemented()
    
    def send_command(self, command: str, args = {}, wait_for_reply=True):
        """
        Execute command with args
        """
        raise NotImplemented()

    def set_power(self, zone: int, power: bool):
        """
        Turn zone on or off
        :param zone: 1, 2, 3
        :param power: True to turn on, False to turn off
        """
        raise NotImplemented()

    def set_mute(self, zone: int, mute: bool):
        """
        Mute zone on or off
        :param zone: 1, 2, 3
        :param mute: True to mute, False to unmute
        """
        raise NotImplemented()

    def set_volume(self, zone: int, level: int):
        """
        Set volume for zone
        :param zone: 1, 2, 3
        :param level: integer from 0 to 100???
        """
        raise NotImplemented()

    def volume_up(self, zone: int):
        """Increase volume for zone by one step"""
        raise NotImplemented()

    def volume_down(self, zone: int):
        """Decrease volume for zone by one step"""
        raise NotImplemented()

    def set_source(self, zone: int, source: int):
        """
        Set source for zone
        :param zone: 1, 2, 3
        :param source: integer from 0 to 9
        """
        raise NotImplemented()

    def zone_status(self, zone: int) -> dict:
        """Return a dictionary containing status details for the zone"""
        raise NotImplemented()


def _prepare_config(amp_series, serial_config_overrides):
    # sanity check the provided amplifier type
    config = DEVICE_CONFIG[amp_series]
    if not config:
        LOG.error(f"Invalid Anthem amp series '{amp_series}', cannot get controller!")
        return (None, None, None)

    protocol_type = config['rs232_protocol']

    # merge any serial initialization changes from the client
    serial_config = config['rs232_defaults']
    if serial_config_overrides:
        serial_config.update( serial_config_overrides )

    return (config, protocol_type, serial_config)

def _format(protocol_type: str, format_code: str, args = {}):
    config = PROTOCOL_CONFIG[protocol_type]

    command = config['commands'].get(format_code)
    if not command:
        LOG.error("Invalid command format '{format_code}' for protocol {protocol_type}; returning None")
        return None

    command += str(config['command_eol'])
    return command.format(**args).encode('ascii')

def _set_volume_cmd(protocol_type, zone: int, volume: int) -> bytes:
#    assert zone in _get_config(protocol_type, 'zones')
    volume = int(max(0, min(volume, MAX_VOLUME)))
    return _format(protocol_type, 'set_volume', args = { ZONE_KEY: zone, VOLUME_KEY: volume })

def _handle_message(protocol_type, text: str):
    """
    Handles an arbitrary message from the RS232 device. Works both for replies
    to queries as well as streams of messages echoed from a device.
    """
    for pattern_name, pattern in RS232_RESPONSE_PATTERNS[protocol_type].items():
        match = re.match(pattern, text)
        if match:
            LOG.info(f"Response for pattern {pattern_name} for text {text}")
            result = pattern_to_dictionary(protocol_type, match, text)
            LOG.info(f"Parsed response text {text}: {result}")
            return result
    LOG.info(f"Found no pattern matching response: {text}")
    return None

def get_amp_controller(amp_series: str, serial_port_path, serial_config_overrides = {}):
    """
    Return synchronous version of amplifier control interface
    :param serial_port_path: serial port, i.e. '/dev/ttyUSB0'
    :return: synchronous implementation of amplifier control interface
    """

    (config, protocol_type, serial_config) = _prepare_config(amp_series, serial_config_overrides)
    if not config:
        return None

    lock = RLock()
    def synchronized(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return wrapper

    class AmpControlSync(AmpControlBase):

        def __init__(self, protocol_type, serial_client):
            self._protocol_type = protocol_type
            self._serial_client = serial_client
            self._config = PROTOCOL_CONFIG[protocol_type]

        @synchronized
        def is_connected(self):
            self.send_command('query_version')
            version = self._serial_client.read()
            if version:
                # command returns: unit type, version, build date   (AVM 2,Version 1.00,Jun 26 2000)
                connected = '(AVM' in version
                LOG.debug(f"{self._serial_client} is_connected() == {connected} {version}")
                return connected
            return False

        @synchronized
        def send_command(self, command: str, args = {}, wait_for_reply=True):
            cmd = _format(self._protocol_type, command, args)
            self._serial_client.send(cmd)
            if wait_for_reply:
                return self._serial_client.read()

        @synchronized
        def set_power(self, zone: int, power: bool):
            #    assert zone in _get_config(protocol_type, 'zones')
            if power:
                cmd = 'power_on'
            else:
                cmd = 'power_off'
            self.send_command(cmd, args = { ZONE_KEY: zone }, wait_for_reply=False)

        @synchronized
        def set_mute(self, zone: int, mute: bool):
            if mute:
                cmd = 'mute_on'
            else:
                cmd = 'mute_off'
            self.send_command(cmd, args = { ZONE_KEY: zone }, wait_for_reply=False)

        @synchronized
        def set_volume(self, zone: int, volume: int):
            request = _set_volume_cmd(self._protocol_type, zone, volume)
            self._serial_client.send(request)

        @synchronized
        def set_source(self, zone: int, source: int):
            #    assert zone in _get_config(protocol_type, 'zones')
            #    assert source in _get_config(protocol_type, 'sources')
            self.send_command('set_source', args = { ZONE_KEY: zone, SOURCE_KEY: source }, wait_for_reply=False)

        @synchronized
        def volume_up(self, zone: int):
            self.send_command('volume_up', args = { ZONE_KEY: zone }, wait_for_reply=False)

        @synchronized
        def volume_down(self, zone: int):
            self.send_command('volume_down', args = { ZONE_KEY: zone }, wait_for_reply=False)

        @synchronized
        def zone_status(self, zone: int) -> dict:
            """Return a dictionary containing status details for the zone"""
            self.send_command('zone_status', { ZONE_KEY: zone })
            response = self._serial_client.read()
            LOG.debug("Received zone %d status response %s", zone, response)

            if "Main Off" in response:
                return { ZONE_KEY: 1, POWER_KEY: False, MUTE_KEY: True, VOLUME_KEY: 0 }
            elif response == "Zone2 Off":
                return { ZONE_KEY: 2, POWER_KEY: False, MUTE_KEY: True, VOLUME_KEY: 0 }
            elif response == "Zone3 Off":
                return { ZONE_KEY: 3, POWER_KEY: False, MUTE_KEY: True, VOLUME_KEY: 0 }

            result = _handle_message(self._protocol_type, response)
            result[POWER_KEY] = True # must manually inject power status if on, since this is implied by a response
            return result

    serial_client = get_sync_rs232_protocol(serial_port_path, serial_config, PROTOCOL_CONFIG[protocol_type])
    return AmpControlSync(protocol_type, serial_client)

#### ASYNCHRONOUS CLIENT
async def get_async_amp_controller(amp_series, serial_port_path, loop, serial_config_overrides = {}):
    """
    Return asynchronous version of amplifier control interface
    :param serial_port_path: serial port, i.e. '/dev/ttyUSB0'
    :return: asynchronous implementation of amplifier control interface
    """

    (config, protocol_type, serial_config) = _prepare_config(amp_series, serial_config_overrides)
    if not config:
        return None

    class AmpControlAsync(AmpControlBase):
        def __init__(self, protocol_type, serial_client):
            self._protocol_type = protocol_type
            self._serial_client = serial_client

        async def send_command(self, command: str, args = {}, wait_for_reply=False):
            cmd = _format(self._protocol_type, command, args)
            LOG.debug("Sending command %s", cmd)
            await self._serial_client.send(cmd)

            LOG.debug(f"Waiting for reply for {cmd}...")
            response = await asyncio.wait_for( self._protocol.read(), 1.0 )
            # response = await self._protocol.read()

            LOG.debug(f"Received {cmd} response: {response}")
            return response

        async def is_connected(self):
            version = await self.send_command('query_version', wait_for_reply=True)
            if version:
                # returns: unit type, version, build date   (AVM 2,Version 1.00,Jun 26 2000)
                LOG.debug(f"amp.is_connected returned {version}")
                return version.contain('(')
            return False

        async def set_power(self, zone: int, power: bool):
            if power:
                cmd = 'power_on'
            else:
                cmd = 'power_off'
            await self.send_command(cmd, args = { ZONE_KEY: zone }, wait_for_reply=False)

            # FIXME: move out of this "generic" code as it should be agnostic to the amp
            # special case for powering on, since Anthem amps can't accept more RS232 requests
            # for several seconds after powering up
            #if request in [ "P1P1\n", "P2P1\n", "P1P3\n" ]:
            if cmd == 'power_on':
                self._serial_client.delay_requests(2.0) # self._config['delay_after_power_on']

        async def set_mute(self, zone: int, mute: bool):
            if mute:
                cmd = 'mute_on'
            else:
                cmd = 'mute_off'
            await self.send_command(cmd, args = { ZONE_KEY: zone }, wait_for_reply=False)

        async def set_volume(self, zone: int, volume: int):
            request = _set_volume_cmd(self._protocol_type, zone, volume)
            await self._serial_client.send(request, wait_for_reply=False)

        async def set_source(self, zone: int, source: int):
            await self.send_command('set_source', args = { ZONE_KEY: zone, SOURCE_KEY: source }, wait_for_reply=False)

        async def volume_up(self, zone: int):
            await self.send_command('volume_up', args = { ZONE_KEY: zone }, wait_for_reply=False)

        async def volume_down(self, zone: int):
            await self.send_command('volume_down', args = { ZONE_KEY: zone }, wait_for_reply=False)

        async def zone_status(self, zone: int) -> dict:
            """Return a dictionary containing status details for the zone"""
            response = await self.send_command('zone_status', { ZONE_KEY: zone })

            if "Main Off" in response:
                return { ZONE_KEY: 1, POWER_KEY: False }
            elif response == "Zone2 Off":
                return { ZONE_KEY: 2, POWER_KEY: False }
            elif response == "Zone3 Off":
                return { ZONE_KEY: 3, POWER_KEY: False }

            result = _handle_message(self._protocol_type, response)  # FIXME: hint at which response pattern to match
            result[POWER_KEY] = True # manually inject power status, since this is implied by this response
            return result


    serial_client = await get_async_rs232_protocol(serial_port_path, serial_config, PROTOCOL_CONFIG[protocol_type], loop)
    return AmpControlAsync(protocol_type, serial_client)