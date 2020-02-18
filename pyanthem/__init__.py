import asyncio
import functools
import logging
import re
import serial
from functools import wraps
from threading import RLock

# FIXME:
# The Anthem has the ability to set a "transmit" status on its RS232 port, which, acc'd the documentation, causes the unit to send ASCII data out any time it's state is changes, either by manual adjustment of the front panel or by the transmission of RS232 commands.
#
# - should we limit MAX volume by default; and have a way to disable 'safety'?
#   could be an issue with damaging speakers

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
        'power_on':       'P{zone}P1',   # zone = 1 (main), 2, 3
        'power_off':      'P{zone}P0',
        'power_status':   'P{zone}P?',   # returns: P{zone}P{on_off}

        'zone_status':    'P{zone}?',    # returns P{source}V{volume}M{mute}

        'set_volume':     'P{zone}VM{volume}', # volume (format sxx.x) = volume to sxx.xx dB where sxx.x = MainMaxVol to -95.5 dB in 0.5 dB steps
        'volume_up':      'P{zone}VMU',
        'volume_down':    'P{zone}VMD',
        'volume_status':  'P{zone}VM?',  # returns: P{zone}VM{sxx.x}

        'mute_on':        'P{zone}M1',
        'mute_off':       'P{zone}M0',
        'mute_toggle':    'P{zone}MT',
        'mute_status':    'P{zone}M?',   # returns: P{zone}M{on_off}

        'source_select':  'P{zone}S{source}',
        'source_status':  'P{zone}S?',  # unknown if this works

        'trigger_on':     't{trigger}T1',
        'trigger_off':    't{trigger}T0',

        'fm_tune':        'TFT{channel}',   # channel = xxx.x (87.5 to 107.9, in 0.1 MHz step)
        'fm_preset':      'TFP{bank}{preset}',
        'am_tune':        'TAT{channel:04}',   # channel = xxxxs (540 to 1600, in 10 KHz step)
        'am_preset':      'TAP{bank}{preset}',
        'tuner_frequeny': 'TT?',            # returns TATxxxx or TFTxxx.x where
        'tuner_up':       'T+',
        'tuner_down':     'T-',

        'sleep_timer':    'P1Z{sleep_mode}', # 0 = off; 1 = 30 min; 2 = 60 min; 3 = 90 min

        'headphone_status': 'H?', # returns HS{source}V{volume}M{mute}
        'headphone_volume_up': 'HVU',
        'headphone_volume_down': 'HVD',
        'headphone_mute_on': 'HM1',
        'headphone_mute_off': 'HM0',
        'headphone_mute_toggle': 'HMT',

        'set_time_format': 'STF{on_off}', # on = 24 hour, off = 12 hour
        'set_time':  'STC{hour:02}:{min:02}', # 00:00 to 23:59 (24hr format) or 12:00AM to 11:59PM (12hr format)
        'set_day_of_week':  'STD{dow}',  # dow = 1 (Sunday) to 7 (Saturday)

        'set_baud_rate':    'SSB{baud_rate}', # baud_rate = 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200
        'version':  '?', # returns: unit type, revision# , build date (e.g. "AVM 2,Version 1.00,Jun 26 2000"
    }
}

AMP_CONFIG ={
    ANTHEM_D2: {
        'command_eol':    "\n",  # x0A (Carriage Return at the end of the string
        'multi-seperator': ';',
        'sources': {
            '0': 'CD',
            '1': 'STEREO',
            '2': '6CH',
            '3': 'TAPE',
            '4': 'TUNER',

            '5': 'DVD',
            'd': 'DVD 2',
            'e': 'DVD 3',
            'f': 'DVD 4',

            '6': 'TV',
            'g': 'TV 2',
            'h': 'TV 3',
            'i': 'TV 4',

            '7': 'SAT',
            'j': 'SAT 2',

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
    config = AMP_CONFIG.get(amp_type)
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
    command = RS232_COMMANDS[amp_type].get(format_code) + str(eol)
    return command.format(**args).encode('ascii')

def _set_power_cmd(amp_type, zone: int, power: bool) -> bytes:
#    assert zone in _get_config(amp_type, 'zones')
    if power:
        return _format(amp_type, 'power_on', args = { 'zone': zone })
    else:
        return _format(amp_type, 'power_off', args = { 'zone': zone })

def _set_mute_cmd(amp_type, zone: int, mute: bool) -> bytes:
#    assert zone in _get_config(amp_type, 'zones')
    if mute:
        return _format(amp_type, 'mute_on', args = { 'zone': zone })
    else:
        return _format(amp_type, 'mute_off', args = { 'zone': zone })
    
def _set_volume_cmd(amp_type, zone: int, volume: int) -> bytes:
#    assert zone in _get_config(amp_type, 'zones')
    volume = int(max(0, min(volume, MAX_VOLUME)))
    return _format(amp_type, 'set_volume', args = { 'zone': zone, 'volume': volume })

def _set_volume_cmd(amp_type, zone: int, volume: int) -> bytes:
#    assert zone in _get_config(amp_type, 'zones')
    volume = int(max(0, min(volume, MAX_VOLUME)))
    return _format(amp_type, 'set_volume', args = { 'zone': zone, 'volume': volume })

def _set_source_cmd(amp_type, zone: int, source: int) -> bytes:
#    assert zone in _get_config(amp_type, 'zones')
#    assert source in _get_config(amp_type, 'sources')
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

            eol = _get_config(self._amp_type, 'command_eol')
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
                                                      functools.partial(AmpControlProtocol, AMP_CONFIG.get(amp_type), loop),
                                                      port_url,
                                                      **SERIAL_INIT_ARGS)
    return AmpControlAsync(amp_type, protocol)
