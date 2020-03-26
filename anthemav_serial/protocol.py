import logging

import asyncio
import functools
import serial
from serial_asyncio import create_serial_connection

LOG = logging.getLogger(__name__)

CONF_EOL = 'command_eol'

async def get_async_rs232_protocol(serial_port_url, serial_config, protocol_config, loop):

    class RS232ControlProtocol(asyncio.Protocol):
        def __init__(self, serial_port_url, protocol_config, loop):
            super().__init__()

            self._serial_port_url = serial_port_url
            self._config = protocol_config
            self._loop = loop

            self._timeout = self._config.get('timeout')
            if self._timeout is None:
                self._timeout = 1.0 # default to 1 second if None
            LOG.info("Timeout set to {self._timeout}")

            self._lock = asyncio.Lock()
            self._transport = None
            self._connected = asyncio.Event(loop=loop)
            self._q = asyncio.Queue(loop=loop)

        def connection_made(self, transport):
            self._transport = transport
            self._connected.set()
            LOG.debug(f"Port {self._serial_port_url} opened {self._transport}")

        def data_received(self, data):
            LOG.debug(f"Received data from port: {data}")
            LOG.debug("Received data from port: %s", data.decode('latin-9'))
            LOG.debug("Received data from port: %s", data.decode('utf-8'))
            asyncio.ensure_future(self._q.put(data), loop=self._loop)

        def connection_lost(self, exc):
            LOG.debug(f"Port {self._serial_port_url} closed")

        async def send(self, request: bytes, skip=0):
            result = bytearray()
            eol = self._config[CONF_EOL]

            await self._connected.wait()

            # only one write/read at a time
            with (await self._lock):
                # clear all buffers of any data waiting to be read before sending the request
                self._transport.serial.reset_output_buffer()
                self._transport.serial.reset_input_buffer()
                while not self._q.empty():
                    self._q.get_nowait()

                # send the request
                LOG.debug("Sending RS232 data %s", request)
                self._transport.write(request)

                # read the response
                LOG.debug("Reading RS232 response...")
                try:
                    while True:
                        result += await asyncio.wait_for(self._q.get(), self._timeout, loop=self._loop)
                        LOG.debug("Partial receive %s", bytes(result).decode('ascii'))
                        if len(result) > skip and result[-len(eol):] == eol:
                            ret = bytes(result)
                            LOG.debug('Received "%s"', ret)
                            return ret.decode('ascii')
                except asyncio.TimeoutError:
                    LOG.error("Timeout receiving response for '%s': received='%s'", request, result)
                    raise

    factory = functools.partial(RS232ControlProtocol, serial_port_url, protocol_config, loop)
    LOG.debug("Creating RS232 connection to {serial_port_url}: {serial_config}")
    _, protocol = await create_serial_connection(loop, factory, serial_port_url, **serial_config)
    return protocol
