import asyncio
import functools
import logging
import re
import serial
from functools import wraps
from threading import RLock

from .protocol import get_rs232_async_protocol

# FIXME:
# The Anthem has the ability to set a "transmit" status on its RS232 port, which, acc'd the documentation, causes the unit to send ASCII data out any time it's state is changes, either by manual adjustment of the front panel or by the transmission of RS232 commands.
#
# - should we limit MAX volume by default; and have a way to disable 'safety'?
#   could be an issue with damaging speakers

LOG = logging.getLogger(__name__)

ANTHEM_D2    = 'd2'    # D2, D2v, D2v 3D
ANTHEM_D1    = 'd1'
ANTHEM_AVM20 = 'avm20'
ANTHEM_AVM30 = 'avm30'
ANTHEM_AVM50 = 'avm50'
ANTHEM_AVM60 = 'avm50'
ANTHEM_MRX   = 'mrx'   # MRX 300, 500, 700
ANTHEM_MRX1  = 'mrx1'  # MRX 310, 510, 710
ANTHEM_MRX2  = 'mrx2'  # MRX 320, 520, 720
ANTHEM_STR   = 'str'

# FIXME: ideally all the config would move to YAML or JSON (RS232 commands, models, etc) which
# would also allow other Anthem non-Python clients to share this info.

ANTHEM_RS232_GEN1 = 'anthem_gen1'
ANTHEM_RS232_GEN2 = 'anthem_gen2'

ANTHEM_SERIES_CONFIG = {
    ANTHEM_D2:    
        { 'protocol': ANTHEM_RS232_GEN1,
          'name': "Anthem D2" },
    ANTHEM_D1:    
        { 'protocol': ANTHEM_RS232_GEN1,
          'name': "Anthem D1" },
    ANTHEM_AVM50: 
        { 'protocol': ANTHEM_RS232_GEN1,
          'name': "Anthem AVM50" },
    ANTHEM_AVM30: 
        { 'protocol': ANTHEM_RS232_GEN1,
          'name': "Anthem AVM30" },
    ANTHEM_AVM20: 
        { 'protocol': ANTHEM_RS232_GEN1,
          'name': "Anthem AVM20" },
    ANTHEM_AVM60: 
        { 'protocol': ANTHEM_RS232_GEN2,
          'name': "Anthem AVM60" },
    ANTHEM_MRX:   
        { 'protocol': ANTHEM_RS232_GEN1,
          'name': "Anthem MRX" },
    ANTHEM_MRX1:  
        { 'protocol': ANTHEM_RS232_GEN2,
          'name': "Anthem MRX1" },
    ANTHEM_MRX2:  
        { 'protocol': ANTHEM_RS232_GEN2,
          'name': "Anthem MRX2" },
    ANTHEM_STR:   
        { 'protocol': ANTHEM_RS232_GEN2,
          'name': "Anthem STR" }
}
SUPPORTED_ANTHEM_SERIES = ANTHEM_SERIES_CONFIG.keys()

RS232_COMMANDS = {
    ANTHEM_RS232_GEN1: {
        'power_on':       'P{zone}P1',   # zone = 1 (main), 2, 3
        'power_off':      'P{zone}P0',
        'power_status':   'P{zone}P?',   # returns: P{zone}P{on_off}

        'zone_status':    'P{zone}?',    # returns P{zone}S{source}V{volume}M{mute}

        # set volume to sxx.xx dB where sxx.x = MainMaxVol to -95.5 dB in 0.5 dB steps
        'set_volume':     'P{zone}VM{volume}', 
        'volume_up':      'P{zone}VMU',
        'volume_down':    'P{zone}VMD',
        'volume_status':  'P{zone}VM?',  # returns: P{zone}VM{sxx.x}

        'mute_on':        'P{zone}M1',
        'mute_off':       'P{zone}M0',
        'mute_toggle':    'P{zone}MT',
        'mute_status':    'P{zone}M?',   # returns: P{zone}M{on_off}

        'source_select':  'P{zone}S{source}',
        'multi_source_select': 'P{zone}X{video_source}{audio_source}',
        'zone_source':    'P{zone}S?',  # unknown if this works

        'trigger_on':     't{trigger}T1',
        'trigger_off':    't{trigger}T0',

        'fm_tune':        'TFT{channel}',      # channel = xxx.x (87.5 to 107.9, in 0.1 MHz step)
        'fm_preset':      'TFP{bank}{preset}',
        'am_tune':        'TAT{channel:04}',   # channel = xxxxs (540 to 1600, in 10 KHz step)
        'am_preset':      'TAP{bank}{preset}',
        'tuner_frequeny': 'TT?',               # returns TATxxxx or TFTxxx.x where
        'tuner_up':       'T+',
        'tuner_down':     'T-',
        'seek_up':        'T+',
        'seek_down':      'T-',

        # Dolby Digital mode dynamic range; 0 = normal; 1 = reduced; 2 = late night
        'set_dynamic_range': 'P{zone}C{range}',

        'display_message':   'P{zone}x{row}{message}', # row = 1 or 2

        'source_seek_up':    'P{zone}SS+',
        'source_seek_down':  'P{zone}SS-',

        'sleep_timer':       'P1Z{sleep_mode}', # 0 = off; 1 = 30 min; 2 = 60 min; 3 = 90 min

        'headphone_status':      'H?', # returns HS{source}V{volume}M{mute}
        'headphone_volume':      'HV{db}', 
        'headphone_volume_up':   'HVU',
        'headphone_volume_down': 'HVD',
        'headphone_mute_on':     'HM1',
        'headphone_mute_off':    'HM0',
        'headphone_mute_toggle': 'HMT',

        'set_time_format': 'STF{on_off}', # on = 24 hour, off = 12 hour
        'set_time':        'STC{hour:02}:{min:02}', # 00:00 to 23:59 (24hr format); 12:00AM to 11:59PM (12hr format)
        'set_day_of_week': 'STD{dow}',  # dow = 1 (Sunday) to 7 (Saturday)

        # baud_rate = 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200
        'set_baud_rate':   'SSB{baud_rate}',

        # returns: unit type, revision# , build date (AVM 2,Version 1.00,Jun 26 2000)
        'query_version':   '?',
        
        'rename_source':   'SN{source}{name}', # 6 character name
        
        'lock_front_panel':   'FPL1',
        'unlock_front_panel': 'FPL0',
    },

    ANTHEM_RS232_GEN2: {
        'power_on':       'Z{zone}POW1', # zone = 1 (main), 2, 3
        'power_off':      'Z{zone}POW0',
        'power_status':   'Z{zone}POW?',

        'zone_status':    'P{zone}?',

        # set volume to sxx.xx dB where sxx.x = MainMaxVol to -95.5 dB in 0.5 dB steps
        'set_volume':     'Z{zone}VOL{volume}', 
        'volume_up':      'Z{zone}VUP',
        'volume_down':    'Z{zone}VDN',
        'volume_status':  'Z{zone}VOL?',

        'mute_on':        'Z{zone}MUT1',
        'mute_off':       'Z{zone}MUT0',
        'mute_toggle':    'Z{zone}MUTt',
        'mute_status':    'Z{zone}MUT?',

        'arc_on':         'Z1ARC1',
        'arc_off':        'Z1ARC0',

        'source_select':  'Z{zone}INP{source}',
        'source_status':  'Z{zone}INP?',

        'trigger_on':     'R{trigger}SET1',
        'trigger_off':    'R{trigger}SET0',

        'fm_tune':        'T1FMS{channel}',      # channel = xxx.x (87.5 to 107.9, in 0.1 MHz step)
        'fm_status':      'T1FMS?',
        'fm_preset':      'T1PSL{preset}',
        'tuner_up':       'T1TUP',
        'tuner_down':     'T1TDN',
        'seek_up':        'T1KUP',
        'seek_down':      'T1KDN',
        'preset_up':      'T1PUP',
        'preset_down':    'T1PDN',

        'display_message':   'Z1MSG{row}{message}', # row = 1 or 2

        'source_seek_up':    'P{zone}SS+',
        'source_seek_down':  'P{zone}SS-',

        # baud_rate = 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200
        'set_baud_rate':   'SSB{baud_rate}',

        # returns: unit type, revision# , build date (IDQMRX 1120 US 0.2.3Oct 23 2015)"
        'query_version':   'IDQ?',
        'query_model':     'IDM?',
        'query_id':        'IDN?',

        'set_echo':        'ECH{on_off}',

        'rename_source':   'SN{source}{name}', # 6 character name
        
        'lock_front_panel':   'FPL1',
        'unlock_front_panel': 'FPL0',
    }
}

# ideally the following would be pre-compiled (re.compile)
RS232_RESPONSES = {
    ANTHEM_RS232_GEN1: {
        'zone_status':       "P(?P<zone>[0-3])S(?P<source>[0-9a-z]}V(?P<volume>[0-9\.]+)M(?P<mute>[01])",
        'volume_status':     "P(?P<zone>[0-3])V(?P<volume>[0-9\.]+)",
        'power_status':      "P(?P<zone>[0-3])P(?P<power>[01])",
        'mute_status':       "P(?P<zone>[0-3])M(?P<mute>[01])",
        'source_status':     "P(?P<zone>[0-3])S(?P<source>[0-9a-z]}",
        'tuner_am':          "TAT(?P<am_freq>\d+)",
        'tuner_fm':          "TFT(?P<fm_freq>[0-9\.]+)",
        'headphone_status':  "(?P<zone>[H])S(?P<source>[0-9a-z]}V(?P<volume>[0-9\.]+)M(?P<mute>[01])",
    },

    ANTHEM_RS232_GEN2: {
        'power_status':      "Z(?P<zone>[0-3])POW(?P<power>[01])",
        'volume_status':     "Z(?P<zone>[0-3])VOL(?P<volume>)[0-9\-]+)",
        'mute_status':       "Z(?P<zone>[0-3])MUT(?P<mute>)[01])",
        'query_model':       "IDM(?P<model>.+)",
        'zone_source':       "Z(?P<zone>[0-3])INP(?P<input>.+)",
        'tuner_fm':          "T(?P<zone>[0-3])FMS(?P<fm_freq>[0-9\.]+)"
    }
}

MAX_VOLUME = 100   # FIXME: range or explicit values should be configurated by amp models

AMP_CONFIG ={
    ANTHEM_RS232_GEN1: {
        'command_eol':    "\n",  # x0A (Carriage Return at the end of the string
        'multi-seperator': ';',
        'default_baud_rate': 9600,
        'sources': { # FIXME: read from yaml?
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
    },
    
    ANTHEM_RS232_GEN2: {
        'command_eol':    "\n",  # x0A (Carriage Return at the end of the string
        'multi-seperator': ';',
        'default_baud_rate': 115200
    }
}

def _get_config(protocol_type: str, key: str):
    config = AMP_CONFIG.get(protocol_type)
    if config:
        return config.get(key)
    LOG.error("Invalid amp type '%s' config key '%s'; returning None", protocol_type, key)
    return None

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
    eol = _get_config(protocol_type, 'command_eol')
    command = RS232_COMMANDS[protocol_type].get(format_code) + str(eol)
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
    for patterns in RS232_RESPONSES.values():
        for name, pattern in patterns:
            patterns[name] = re.compile(pattern)

def _handle_message(protocol_type, text: str):
    """
    Handles an arbitrary message from the RS232 device. Works both for replies
    to queries as well as streams of messages echoed from a device.
    """
    # 1 find the matching message
    # 2 parse or dispatch
    for pattern in RS232_RESPONSES[protocol_type].values:
        p = re.compile(pattern) # FIXME: ideally pre-compile
        if p.match:
            result = re.match(p, text)


def get_amp_controller(amp_series: str, port_url, serial_config_overrides = {}):
    """
    Return synchronous version of amplifier control interface
    :param port_url: serial port, i.e. '/dev/ttyUSB0'
    :return: synchronous implementation of amplifier control interface
    """

    # sanity check the provided amplifier type
    if amp_series not in SUPPORTED_ANTHEM_SERIES:
        LOG.error("Unsupported amplifier series '%s'", amp_series)
        return None

    protocol_type = ANTHEM_SERIES_CONFIG[amp_series].get('protocol')
    
    # merge any serial initialization changes from the client
    rs232_config = ANTHEM_SERIES_CONFIG[amp_series].get('rs232')
    serial_config = rs232_config['serial_defaults']
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

            eol = _get_config(self._protocol_type, 'command_eol')
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
    if amp_series not in SUPPORTED_ANTHEM_SERIES:
        LOG.error("Unsupported amplifier series '%s'", amp_series)
        return None

    config = ANTHEM_SERIES_CONFIG[amp_series]
    protocol_type = config.get('protocol')

    # merge any serial initialization changes from the client
    rs232_config = ANTHEM_SERIES_CONFIG[amp_series].get('rs232')
    serial_config = rs232_config['serial_defaults']
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
