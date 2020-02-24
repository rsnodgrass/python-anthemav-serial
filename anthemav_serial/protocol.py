import logging

import asyncio
import functools
import serial
from serial_asyncio import create_serial_connection

LOG = logging.getLogger(__name__)

CONF_EOL = 'eol'

DEFAULT_SERIAL_CONFIG = {
    'baudrate':      9600,
    'bytesize':      serial.EIGHTBITS,
    'parity':        serial.PARITY_NONE,
    'stopbits':      serial.STOPBITS_ONE,
    'timeout':       1.0,
    'write_timeout': 1.0
}

DEFAULT_PROTOCOL_CONFIG = {
    'eol': "\n"
}

# FIXME: there should be an impl of this somewhere, ideally without the send/response pattern only

async def get_rs232_async_protocol(serial_port_url, serial_config, protocol_config, loop):

    class RS232ControlProtocol(asyncio.Protocol):
        def __init__(self, serial_port_url, protocol_config, loop):
            super().__init__()

            self._serial_port_url = serial_port_url
            self._config = protocol_config
            self._loop = loop

            self._timeout = self._config.get('timeout')

            self._lock = asyncio.Lock()
            self._transport = None
            self._connected = asyncio.Event(loop=loop)
            self._q = asyncio.Queue(loop=loop)

        def connection_made(self, transport):
            self._transport = transport
            self._connected.set()
            LOG.debug(f"Port {self._serial_port_url} opened {self._transport}")

        def data_received(self, data):
            asyncio.ensure_future(self._q.put(data), loop=self._loop)

        async def send(self, request: bytes, skip=0):
            await self._connected.wait()
            result = bytearray()

            eol = self._config.get(CONF_EOL)
            if eol == None:
                eol = '\n'
            len_eol = len(eol)

            # only one write/read at a time
            with (await self._lock):
                self._transport.serial.reset_output_buffer()
                self._transport.serial.reset_input_buffer()

                # send the request
                while not self._q.empty():
                    self._q.get_nowait()
                self._transport.write(request)

                # read the response
                try:
                    while True:
                        result += await asyncio.wait_for(self._q.get(), self._timeout, loop=self._loop)
                        if len(result) > skip and result[-len_eol:] == eol:
                            ret = bytes(result)
                            LOG.debug('Received "%s"', ret)
                            return ret.decode('ascii')
                except asyncio.TimeoutError:
                    LOG.error("Timeout receiving response for '%s': received='%s'", request, result)
                    raise

    factory = functools.partial(RS232ControlProtocol, serial_port_url, protocol_config, loop)
    _, protocol = await create_serial_connection(loop, factory, serial_port_url, **serial_config)
    return protocol