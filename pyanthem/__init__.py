import asyncio
import functools
import logging
import re
import serial
from functools import wraps
from threading import RLock

LOG = logging.getLogger(__name__)

MAX_VOLUME = 100

# currently the D1 and AVM models support same protocols as D2
# however, we may change the this as there is more complex
# configuration needed in the future
ANTHEM_D2 = 'anthem-d2'
ANTHEM_D1 = 'anthem-d2'
ANTHEM_AVM20 = 'anthem-d2'
ANTHEM_AVM30 = 'anthem-d2'
SUPPORTED_AMP_TYPES = [ ANTHEM_D2 ]

# technically zone = {amp_number}{zone_num_within_amp_1-6} (e.g. 11 = amp number 1, zone 1)
RS232_COMMANDS = {
    ANTHEM_D2: {        
        'power_on':       'P{zone}P1', # zone = 1 (main), 2, 3
        'power_off':      'P{zone}P0',

        'set_volume':     'P{zone}VM{volume}',
        'volume_up':      'P{zone}VMU',
        'volume_down':    'P{zone}VMD',

        'mute_on':        'P{zone}M1',
        'mute_off':       'P{zone}M0',
        'mute_toggle':    'P{zone}MT',

        'source_select':  'P{zone}S{source}',

        'tune_up':        'T+',
        'tune_down':      'T-',

        'set_fm':         'TFT{channel}',   # channel = 4 digits
        'set_am':         'TAT{channel}',   # channel = 4 digits
    }
}

PROTOCOL_CONFIG ={
    ANTHEM_D2: {
        'protocol_eol':    b'\x0a',
        'sources': {
            '0': 'CD',
            '1': 'STEREO',
            '2': '6CH',
            '3': 'TAPE',
            '4': 'TUNER',
            '5': 'DVD',
            '6': 'TV',
            '7': 'SAT',
            '8': 'VCR',
            '9': 'AUX'
        }
    }
}

TIMEOUT = 2  # serial operation timeout (seconds)

SERIAL_INIT_ARGS = {
    'baudrate':      19200,
    'bytesize':      serial.EIGHTBITS,
    'parity':        serial.PARITY_NONE,
    'stopbits':      serial.STOPBITS_ONE,
    'timeout':       TIMEOUT,
    'write_timeout': TIMEOUT
}

def _get_config(amp_type: str, key: str):
    config = AMP_TYPE_CONFIG.get(amp_type)
    if config:
        return config.get(key)
    LOG.error("Invalid amp type '%s' config key '%s'; returning None", amp_type, key)
    return None

class AmpControlBase(object):
    """
    AmpliferControlBase amplifier interface
    """

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

    def set_source(self, zone: int, source: int):
        """
        Set source for zone
        :param zone: 1, 2, 3
        :param source: integer from 0 to 9
        """
        raise NotImplemented()

def _format(amp_type: str, format_code: str, args = {}):
    eol = _get_config(amp_type, 'command_eol')
    command = RS232_COMMANDS[amp_type].get(format_code) + eol
    return command.format(**args).encode('ascii')

def _set_power_cmd(amp_type, zone: int, power: bool) -> bytes:
    assert zone in _get_config(amp_type, 'zones')
    if power:
        return _format(amp_type, 'power_on', args = { 'zone': zone })
    else:
        return _format(amp_type, 'power_off', args = { 'zone': zone })

def _set_mute_cmd(amp_type, zone: int, mute: bool) -> bytes:
    assert zone in _get_config(amp_type, 'zones')
    if mute:
        return _format(amp_type, 'mute_on', args = { 'zone': zone })
    else:
        return _format(amp_type, 'mute_off', args = { 'zone': zone })
    
def _set_volume_cmd(amp_type, zone: int, volume: int) -> bytes:
    assert zone in _get_config(amp_type, 'zones')
    volume = int(max(0, min(volume, MAX_VOLUME)))
    return _format(amp_type, 'set_volume', args = { 'zone': zone, 'volume': volume })

def _set_volume_cmd(amp_type, zone: int, volume: int) -> bytes:
    assert zone in _get_config(amp_type, 'zones')
    volume = int(max(0, min(volume, MAX_VOLUME)))
    return _format(amp_type, 'set_volume', args = { 'zone': zone, 'volume': volume })

def _set_source_cmd(amp_type, zone: int, source: int) -> bytes:
    assert zone in _get_config(amp_type, 'zones')
    assert source in _get_config(amp_type, 'sources')
    return _format(amp_type, 'set_source', args = { 'zone': zone, 'source': source })

def get_amp_controller(amp_type: str, port_url):
    """
    Return synchronous version of amplifier control interface
    :param port_url: serial port, i.e. '/dev/ttyUSB0'
    :return: synchronous implementation of amplifier control interface
    """

    # sanity check the provided amplifier type
    if amp_type not in SUPPORTED_AMP_TYPES:
        LOG.error("Unsupported amplifier type '%s'", amp_type)
        return None

    lock = RLock()

    def synchronized(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return wrapper

    class AmpControlSync(AmpControlBase):
        def __init__(self, amp_type, port_url):
            self._amp_type = amp_type
            self._port = serial.serial_for_url(port_url, **SERIAL_INIT_ARGS)

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

            eol = _get_config(self._amp_type, 'protocol_eol')
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
        def set_power(self, zone: int, power: bool):
            self._process_request(_set_power_cmd(self._amp_type, zone, power))

        @synchronized
        def set_mute(self, zone: int, mute: bool):
            self._process_request(_set_mute_cmd(self._amp_type, zone, mute))

        @synchronized
        def set_volume(self, zone: int, volume: int):
            self._process_request(_set_volume_cmd(self._amp_type, zone, volume))

        @synchronized
        def set_source(self, zone: int, source: int):
            self._process_request(_set_source_cmd(self._amp_type, zone, source))

    return AmpControlSync(amp_type, port_url)



@asyncio.coroutine
def get_async_amp_controller(amp_type, port_url, loop):
    """
    Return asynchronous version of amplifier control interface
    :param port_url: serial port, i.e. '/dev/ttyUSB0'
    :return: asynchronous implementation of amplifier control interface
    """
    from serial_asyncio import create_serial_connection

    # sanity check the provided amplifier type
    if amp_type not in SUPPORTED_AMP_TYPES:
        LOG.error("Unsupported amplifier type '%s'", amp_type)
        return None

    lock = asyncio.Lock()

    def locked_coro(coro):
        @asyncio.coroutine
        @wraps(coro)
        def wrapper(*args, **kwargs):
            with (yield from lock):
                return (yield from coro(*args, **kwargs))
        return wrapper

    class AmpControlAsync(AmpControlBase):
        def __init__(self, amp_type, protocol):
            self._amp_type = amp_type
            self._protocol = protocol

        @locked_coro
        @asyncio.coroutine
        def set_power(self, zone: int, power: bool):
            yield from self._protocol.send(_set_power_cmd(self._amp_type, zone, power))

        @locked_coro
        @asyncio.coroutine
        def set_mute(self, zone: int, mute: bool):
            yield from self._protocol.send(_set_mute_cmd(self._amp_type, zone, mute))

        @locked_coro
        @asyncio.coroutine
        def set_volume(self, zone: int, volume: int):
            yield from self._protocol.send(_set_volume_cmd(self._amp_type, zone, volume))

        @locked_coro
        @asyncio.coroutine
        def set_source(self, zone: int, source: int):
            yield from self._protocol.send(_set_source_cmd(self._amp_type, zone, source))

    class AmpControlProtocol(asyncio.Protocol):
        def __init__(self, config, loop):
            super().__init__()
            self._config = config
            self._loop = loop
            self._lock = asyncio.Lock()
            self._transport = None
            self._connected = asyncio.Event(loop=loop)
            self.q = asyncio.Queue(loop=loop)

        def connection_made(self, transport):
            self._transport = transport
            self._connected.set()
            LOG.debug('port opened %s', self._transport)

        def data_received(self, data):
            asyncio.ensure_future(self.q.put(data), loop=self._loop)

        @asyncio.coroutine
        def send(self, request: bytes, skip=0):
            yield from self._connected.wait()
            result = bytearray()

            eol = self._config.get('protocol_eol')
            len_eol = len(eol)

            # Only one transaction at a time
            with (yield from self._lock):
                self._transport.serial.reset_output_buffer()
                self._transport.serial.reset_input_buffer()
                while not self.q.empty():
                    self.q.get_nowait()
                self._transport.write(request)
                try:
                    while True:
                        result += yield from asyncio.wait_for(self.q.get(), TIMEOUT, loop=self._loop)
                        if len(result) > skip and result[-len_eol:] == eol:
                            ret = bytes(result)
                            LOG.debug('Received "%s"', ret)
                            return ret.decode('ascii')
                except asyncio.TimeoutError:
                    LOG.error("Timeout receiving response for '%s': received='%s'", request, result)
                    raise

    _, protocol = yield from create_serial_connection(loop,
                                                      functools.partial(AmpControlProtocol, AMP_TYPE_CONFIG.get(amp_type), loop),
                                                      port_url,
                                                      **SERIAL_INIT_ARGS)
    return AmpControlAsync(amp_type, protocol)