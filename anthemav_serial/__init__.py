import asyncio
import functools
import logging
import re
import os
import serial
import yaml

from functools import wraps
from threading import RLock

from .config import (DEVICE_CONFIG, PROTOCOL_CONFIG, get_with_log)
from .protocol import get_rs232_async_protocol

# FIXME:
# The Anthem has the ability to set a "transmit" status on its RS232 port, which, acc'd the documentation, causes the unit to send ASCII data out any time it's state is changes, either by manual adjustment of the front panel or by the transmission of RS232 commands.
#
# - should we limit MAX volume by default; and have a way to disable 'safety'?
#   could be an issue with damaging speakers

LOG = logging.getLogger(__name__)

MAX_VOLUME = 100   # FIXME: range or explicit values should be configurated by amp models

# ictionary pattern matches for all responses for each protocol
RS232_RESPONSE_PATTERNS = []

class AmpControlBase(object):
    """
    AmpliferControlBase amplifier interface
    """

    def run_command(self, command: str, args = {}):
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

def _format(protocol_type: str, format_code: str, args = {}):
    config = PROTOCOL_CONFIG[protocol_type]

    command = config['commands'].get(format_code)
    if not command:
        LOG.error("Invalid command format '{format_code}' for protocol {protocol_type}; returning None")
        return None

    command += str(config['command_eol'])
    return command.format(**args).encode('ascii')

def _set_power_cmd(protocol_type, zone: int, power: bool) -> bytes:
#    assert zone in _get_config(protocol_type, 'zones')
    if power:
        return _format(protocol_type, 'power_on', args = { 'zone': zone })
    else:
        return _format(protocol_type, 'power_off', args = { 'zone': zone })

def _set_mute_cmd(protocol_type, zone: int, mute: bool) -> bytes:
#    assert zone in _get_config(protocol_type, 'zones')
    if mute:
        return _format(protocol_type, 'mute_on', args = { 'zone': zone })
    else:
        return _format(protocol_type, 'mute_off', args = { 'zone': zone })

def _set_volume_cmd(protocol_type, zone: int, volume: int) -> bytes:
#    assert zone in _get_config(protocol_type, 'zones')
    volume = int(max(0, min(volume, MAX_VOLUME)))
    return _format(protocol_type, 'set_volume', args = { 'zone': zone, 'volume': volume })

def _volume_up_cmd(protocol_type, zone: int) -> bytes:
    return _format(protocol_type, 'volume_up', args = { 'zone': zone })

def _volume_down_cmd(protocol_type, zone: int) -> bytes:
    return _format(protocol_type, 'volume_down', args = { 'zone': zone })

def _set_source_cmd(protocol_type, zone: int, source: int) -> bytes:
#    assert zone in _get_config(protocol_type, 'zones')
#    assert source in _get_config(protocol_type, 'sources')
    return _format(protocol_type, 'set_source', args = { 'zone': zone, 'source': source })

def _precompile_patterns():
    """Precompile all response patterns"""

    for protocol, config in PROTOCOL_CONFIG:
        patterns = []
        for name, pattern in config['responses']:
            patterns[name] = re.compile(pattern)
        RS232_RESPONSE_PATTERNS[protocol] = patterns

def _handle_message(protocol_type, text: str):
    """
    Handles an arbitrary message from the RS232 device. Works both for replies
    to queries as well as streams of messages echoed from a device.
    """

    # pre-compile all patterns if empty
    if not RS232_RESPONSE_PATTERNS:
        _precompile_patterns()

    # FIXME
    # if a matching response is found, dispatch to appropriate handler to update
    # 1 find the matching message
    # 2 parse or dispatch
    for pattern_name, pattern in RS232_RESPONSE_PATTERNS[protocol_type]:
        result = pattern.match
        if result:
            # FIXME: split out all patterns and update by key name
            return None

def get_amp_controller(amp_series: str, port_url, serial_config_overrides = {}):
    """
    Return synchronous version of amplifier control interface
    :param port_url: serial port, i.e. '/dev/ttyUSB0'
    :return: synchronous implementation of amplifier control interface
    """

    # sanity check the provided amplifier type
    config = DEVICE_CONFIG[amp_series]
    if not config:
        LOG.error(f"Unsupported amplifier series '{amp_series}'")
        return None

    protocol_type = config['rs232_protocol']

    # merge any serial initialization changes from the client
    serial_config = config['rs232_defaults']
    serial_config.update( serial_config_overrides )

    lock = RLock()

    def synchronized(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return wrapper

    class AmpControlSync(AmpControlBase):
        def __init__(self, protocol_type, port_url, serial_config):
            self._protocol_type = protocol_type
            self._config = PROTOCOL_CONFIG[protocol_type]
            self._port = serial.serial_for_url(port_url, **serial_config)

        def _process_request(self, request: bytes, skip=0):
            """
            :param request: request that is sent to the xantech
            :param skip: number of bytes to skip for end of transmission decoding
            :return: ascii string returned by xantech
            """
            print('Sending "%s"', request)
            LOG.debug('Sending "%s"', request)

            # clear
            self._port.reset_output_buffer()
            self._port.reset_input_buffer()

            # send
            self._port.write(request)
            self._port.flush()

            eol = self._config['command_eol']
            len_eol = len(eol)

            # receive
            result = bytearray()
            while True:
                c = self._port.read(1)
                if not c:
                    ret = bytes(result)
                    print('Result "%s"', result)
                    LOG.info(result)
                    raise serial.SerialTimeoutException(
                        'Connection timed out! Last received bytes {}'.format([hex(a) for a in result]))
                result += c
                if len(result) > skip and result[-len_eol:] == eol:
                    break

            ret = bytes(result)
            LOG.debug('Received "%s"', ret)
            return ret.decode('ascii')

        @synchronized
        def run_command(self, command: str, args = {}):
            cmd = _format(self._protocol_type, command, args)
            return self._process_request(cmd)

        @synchronized
        def set_power(self, zone: int, power: bool):
            self._process_request(_set_power_cmd(self._protocol_type, zone, power))

        @synchronized
        def set_mute(self, zone: int, mute: bool):
            self._process_request(_set_mute_cmd(self._protocol_type, zone, mute))

        @synchronized
        def set_volume(self, zone: int, volume: int):
            self._process_request(_set_volume_cmd(self._protocol_type, zone, volume))

        @synchronized
        def set_source(self, zone: int, source: int):
            self._process_request(_set_source_cmd(self._protocol_type, zone, source))

        @synchronized
        def volume_up(self, zone: int):
            self.run_command('volume_up', args = { 'zone': zone })

        @synchronized
        def volume_down(self, zone: int):
            self.run_command('volume_down', args = { 'zone': zone })

        def _pattern_to_dictionary(self, pattern: str, text: str) -> dict:
            result = pattern.match(text)
            if not result:
                LOG.error(f"Could not parse '{text}' with pattern '{pattern}'")
                return None

            d = result.groupdict()
            
            # FIXME: for safety, we may want to limit which keys this applies to
            # replace and 0 or 1 with True or False
            for k, v in d.items():
                if v == '0':
                    d[k] = False
                elif v == '1':
                    d[k] = True

            return d

        def zone_status(self, zone: int) -> dict:
            """Return a dictionary containing status details for the zone"""

            # send any commands necessary to get current status for all zones
            commands = [ 'zone_status', 'power_status' ]
            for zone in [ 1, 2, 3 ]:
                for command in commands:
                    self.run_command(command, { 'zone': zone })
            
            # FIXME: read all responses from status inquieres

            return {}

        def _parse_status(self, dict, message):
            # 1 find matching pattern
            # 2 extract variable names into dictionary
            LOG.error(f"Could not parse status message '{message}' into dictionary")


    return AmpControlSync(protocol_type, port_url, serial_config)



async def get_async_amp_controller(amp_series, port_url, loop, serial_config_overrides = {}):
    """
    Return asynchronous version of amplifier control interface
    :param port_url: serial port, i.e. '/dev/ttyUSB0'
    :return: asynchronous implementation of amplifier control interface
    """

    # sanity check the provided amplifier type
    config = DEVICE_CONFIG[amp_series]
    if not config:
        LOG.error(f"Invalid Anthem amp series '{amp_series}', cannot get controller")
        return None

    protocol_type = config['rs232_protocol']

    # merge any serial initialization changes from the client
    serial_config = config['rs232_defaults']
    serial_config.update( serial_config_overrides )
    
    lock = asyncio.Lock()

    def locked_coro(coro):
        """While this is asynchronous, ensure only a single, ordered command is sent to RS232 at a time"""
        @wraps(coro)
        async def wrapper(*args, **kwargs):
            with (await lock):
                return (await coro(*args, **kwargs))
        return wrapper

    class AmpControlAsync(AmpControlBase):
        def __init__(self, protocol_type, protocol):
            self._protocol_type = protocol_type            
            self._protocol = protocol

        @locked_coro
        async def run_command(self, command: str, args = {}):
            await self._protocol.send( _format(self._protocol_type, command, args) )
            
        @locked_coro
        async def set_power(self, zone: int, power: bool):
            await self._protocol.send(_set_power_cmd(self._protocol_type, zone, power))

        @locked_coro
        async def set_mute(self, zone: int, mute: bool):
            await self._protocol.send(_set_mute_cmd(self._protocol_type, zone, mute))

        @locked_coro
        async def set_volume(self, zone: int, volume: int):
            await self._protocol.send(_set_volume_cmd(self._protocol_type, zone, volume))

        @locked_coro
        async def set_source(self, zone: int, source: int):
            await self._protocol.send(_set_source_cmd(self._protocol_type, zone, source))

        @locked_coro
        async def volume_up(self, zone: int):
            await self.run_command('volume_up', args = { 'zone': zone })

        @locked_coro
        async def volume_down(self, zone: int):
            await self.run_command('volume_down', args = { 'zone': zone })

    protocol = get_rs232_async_protocol(port_url, serial_config, config, loop)
    return AmpControlAsync(protocol_type, protocol)
