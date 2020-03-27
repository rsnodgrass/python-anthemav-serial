import logging

import re
import os
import yaml
import time
import serial
import asyncio
import functools

from functools import wraps
from threading import RLock

from .config import (DEVICE_CONFIG, PROTOCOL_CONFIG, get_with_log)
from .protocol import get_async_rs232_protocol

# FIXME:
#  - we may want to throttle the RS232 messages per-second, since rapid sending of commands can cause timeouts

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

# cached dictionary pattern matches for all responses for each protocol
def _precompile_response_patterns():
    """Precompile all response patterns"""
    for protocol_type, config in PROTOCOL_CONFIG.items():
        patterns = {}

#        LOG.debug(f"Precompile patterns for {protocol_type}")
        for name, pattern in config['responses'].items():
#           LOG.debug(f"Precompiling pattern {name}")
            patterns[name] = re.compile(pattern)
        RS232_RESPONSE_PATTERNS[protocol_type] = patterns

RS232_RESPONSE_PATTERNS = {}
_precompile_response_patterns()

class AmpControlBase(object):
    """
    AmpliferControlBase amplifier interface
    """

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
    return _format(protocol_type, 'set_volume', args = { 'zone': zone, 'volume': volume })

def _pattern_to_dictionary(protocol_type, match, source_text: str) -> dict:
    """Convert the pattern to a dictionary, replacing 0 and 1's with True/False"""
    LOG.info(f"Pattern matching {source_text} {match}")
    d = match.groupdict()
            
    # type convert any pre-configured fields
    # TODO: this could be a lot more efficient LOL
    boolean_fields = PROTOCOL_CONFIG[protocol_type].get('boolean_fields')
    for k, v in d.items():
        if k in boolean_fields:
            # replace and 0 or 1 with True or False
            if v == '0':
                d[k] = False
            elif v == '1':
                d[k] = True
    return d

def _handle_message(protocol_type, text: str):
    """
    Handles an arbitrary message from the RS232 device. Works both for replies
    to queries as well as streams of messages echoed from a device.
    """
    for pattern_name, pattern in RS232_RESPONSE_PATTERNS[protocol_type].items():
        match = re.match(pattern, text)
        if match:
            LOG.info(f"Response for pattern {pattern_name} for text {text}")
            result = _pattern_to_dictionary(protocol_type, match, text)
            LOG.info(f"Parsed response text {text}: {result}")
            return result
    LOG.info(f"Found no pattern matching response: {text}")
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
    if serial_config_overrides:
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

            LOG.debug(f"Creating RS232 connection to {port_url}: {serial_config}")
            self._port = serial.serial_for_url(port_url, **serial_config)

        def _send_request(self, request: bytes, wait_for_reply, skip=0):
            """
            :param request: request that is sent to the xantech
            :param skip: number of bytes to skip for end of transmission decoding
            :return: ascii string returned by xantech
            """
            LOG.debug('Sending "%s"', request)

            # clear
            self._port.reset_output_buffer()
            self._port.reset_input_buffer()

            # send
            self._port.write(request)
            self._port.flush()

            eol = self._config['command_eol']
            len_eol = len(eol)

            if not wait_for_reply:
                return

            # receive
            result = bytearray()
            while True:
                c = self._port.read(1)
                if not c:
                    ret = bytes(result)
                    LOG.info("Serial read result: %s", result)
                    raise serial.SerialTimeoutException(
                        'Connection timed out! Last received bytes {}'.format([hex(a) for a in result]))
                result += c
                if len(result) > skip and result[-len_eol:] == eol:
                    break

            ret = bytes(result)
            LOG.debug('Received "%s"', ret)
            return ret.decode('ascii')

        @synchronized
        def send_command(self, command: str, args = {}, wait_for_reply=True):
            cmd = _format(self._protocol_type, command, args)
            return self._send_request(cmd, wait_for_reply)

        @synchronized
        def set_power(self, zone: int, power: bool):
            #    assert zone in _get_config(protocol_type, 'zones')
            if power:
                cmd = 'power_on'
            else:
                cmd = 'power_off'
            self.send_command(cmd, args = { 'zone': zone }, wait_for_reply=False)

        @synchronized
        def set_mute(self, zone: int, mute: bool):
            if mute:
                cmd = 'mute_on'
            else:
                cmd = 'mute_off'
            self.send_command(cmd, args = { 'zone': zone }, wait_for_reply=False)

        @synchronized
        def set_volume(self, zone: int, volume: int):
            request = _set_volume_cmd(self._protocol_type, zone, volume)
            self._send_request(request, False)

        @synchronized
        def set_source(self, zone: int, source: int):
            #    assert zone in _get_config(protocol_type, 'zones')
            #    assert source in _get_config(protocol_type, 'sources')
            self.send_command('set_source', args = { 'zone': zone, 'source': source }, wait_for_reply=False)

        @synchronized
        def volume_up(self, zone: int):
            self.send_command('volume_up', args = { 'zone': zone }, wait_for_reply=False)

        @synchronized
        def volume_down(self, zone: int):
            self.send_command('volume_down', args = { 'zone': zone }, wait_for_reply=False)

        @synchronized
        def zone_status(self, zone: int) -> dict:
            """Return a dictionary containing status details for the zone"""
            response = self.send_command('zone_status', { 'zone': zone })
            LOG.debug("Received zone %d status response %s", zone, response)

            if "Main Off" in response:
                return { "zone": 1, "power": False, "mute": True, "volume": 0 }
            elif response == "Zone2 Off":
                return { "zone": 2, "power": False, "mute": True, "volume": 0 }
            elif response == "Zone3 Off":
                return { "zone": 3, "power": False, "mute": True, "volume": 0 }

            result = _handle_message(self._protocol_type, response)
            result['power'] = True # must manually inject power status if on, since this is implied by a response
            return result

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
    if serial_config_overrides:
        serial_config.update( serial_config_overrides )
    
    lock = asyncio.Lock()

    def locked_coro(coro):
        """While this is asynchronous, ensure only a single, ordered command is sent to RS232 at a time (non-reentrant lock)"""
        @wraps(coro)
        async def wrapper(*args, **kwargs):
            with (await lock):
                return (await coro(*args, **kwargs))
        return wrapper

    class AmpControlAsync(AmpControlBase):
        def __init__(self, protocol_type, protocol):
            self._protocol_type = protocol_type            
            self._protocol = protocol
            self._last_send = time.time() - 1

        # NOTE: Callers of _send_command() shouldn't have @locked_coro, as the lock isn't re-entrant.
        # This almost could move to the protocol layer as only sending/receiving should be locked.
        @locked_coro
        async def send_command(self, command: str, args = {}, wait_for_reply=True):
            cmd = _format(self._protocol_type, command, args)
            response = await self._protocol.send(cmd, wait_for_reply=wait_for_reply)
            LOG.debug(f"Received {cmd} response: {response}")
            return response

        async def set_power(self, zone: int, power: bool):
            if power:
                cmd = 'power_on'
            else:
                cmd = 'power_off'
            await self.send_command(cmd, args = { 'zone': zone }, wait_for_reply=False)

        async def set_mute(self, zone: int, mute: bool):
            if mute:
                cmd = 'mute_on'
            else:
                cmd = 'mute_off'
            await self.send_command(cmd, args = { 'zone': zone }, wait_for_reply=False)

        @locked_coro
        async def set_volume(self, zone: int, volume: int):
            request = _set_volume_cmd(self._protocol_type, zone, volume)
            await self._protocol.send(request, wait_for_reply=False)

        async def set_source(self, zone: int, source: int):
            await self.send_command('set_source', args = { 'zone': zone, 'source': source }, wait_for_reply=False)

        async def volume_up(self, zone: int):
            await self.send_command('volume_up', args = { 'zone': zone }, wait_for_reply=False)

        async def volume_down(self, zone: int):
            await self.send_command('volume_down', args = { 'zone': zone }, wait_for_reply=False)

        async def zone_status(self, zone: int) -> dict:
            """Return a dictionary containing status details for the zone"""
            response = await self.send_command('zone_status', { 'zone': zone })

            if "Main Off" in response:
                return { "zone": 1, "power": False }
            elif response == "Zone2 Off":
                return { "zone": 2, "power": False }
            elif response == "Zone3 Off":
                return { "zone": 3, "power": False }

            result = _handle_message(self._protocol_type, response)  # FIXME: could hint at which response pattern to match
            result['power'] = True # must manually inject power status if on, since this is implied by a response
            return result

    LOG.debug(f"About to connect with {serial_config}")
    protocol = await get_async_rs232_protocol(port_url, serial_config, PROTOCOL_CONFIG[protocol_type], loop)
    return AmpControlAsync(protocol_type, protocol)
