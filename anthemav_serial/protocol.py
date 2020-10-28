import logging

import time
import asyncio
import functools
import serial
from serial_asyncio import create_serial_connection
from ratelimit import limits

LOG = logging.getLogger(__name__)

CONF_EOL = 'command_eol'
CONF_THROTTLE_RATE = 'min_time_between_commands'

DEFAULT_TIMEOUT = 1.0
FIVE_MINUTES = 300

ASCII='ascii'

async def get_async_rs232_protocol(serial_port_path, serial_config, protocol_config, loop):

    # ensure only a single, ordered command is sent to RS232 at a time (non-reentrant lock)
    async def locked_method(method):
        @functools.wraps(method)
        async def wrapper(self, *method_args, **method_kwargs):
            #with (await self._lock):
                return await method(self, *method_args, **method_kwargs)
        return wrapper

    # check if connected, and abort calling provided method if no connection before timeout
    async def ensure_connected(method):
        @functools.wraps(method)
        async def wrapper(self, *method_args, **method_kwargs):
            try:
                await asyncio.wait_for(self._connected.wait(), self._timeout)
            except:
                LOG.debug(f"Timeout waiting to send data to {self._serial_port_path}, no connection!")
                return
            return await method(self, *method_args, **method_kwargs)
        return wrapper

    class RS232ControlProtocol(asyncio.Protocol):
        def __init__(self, serial_port_path, protocol_config, loop):
            super().__init__()

            self._serial_port_path = serial_port_path
            self._config = protocol_config
            self._loop = loop

            self._timeout = self._config.get('timeout', DEFAULT_TIMEOUT)
            self._last_send = time.time() - self._timeout

            self._transport = None
            self._connected = asyncio.Event(loop=self._loop)
            self._q = asyncio.Queue(loop=self._loop)

            # ensure only a single, ordered command is sent to RS232 at a time (non-reentrant lock)
            #self._lock = asyncio.Lock()

            LOG.info(f"RS232ControlProtocol initialized {serial_port_path}")

        def connection_made(self, transport):
            self._transport = transport
            LOG.debug(f"Port {self._serial_port_path} opened: {self._transport}")
            self._connected.set()

        def data_received(self, data):
            LOG.debug(f"Received {self._serial_port_path}: {data}")
#            asyncio.ensure_future(self._q.put(data), loop=self._loop)

        def connection_lost(self, exc):
            LOG.debug(f"Port {self._serial_port_path} closed")

        def delay_requests(self, seconds: float):
            """Throttle future requests for at least the specific seconds since last request"""
            delta_since_last_send = time.time() - self._last_send
            self._last_send = (time.time() - delta_since_last_send) + seconds

        # throttle the number of RS232 sends per second to avoid causing timeouts
        async def _apply_request_throttling(self):
            delay = None
            min_time_between_requests = self._config[CONF_THROTTLE_RATE]
            delta_since_last_send = time.time() - self._last_send

            if delta_since_last_send < 0:
                delay = -1 * delta_since_last_send
            elif delta_since_last_send < min_time_between_requests:
                delay = max(0, min_time_between_requests - delta_since_last_send)
                delay = min(delay, min_time_between_requests)

            if delay > 0:
                LOG.debug(f"Throttling {delay} seconds before sending request")
                await asyncio.sleep(delay)


        #@ensure_connected
        #@locked_method
        async def send(self, request: bytes, skip=0):
            await self._apply_request_throttling()

            # clear all buffers of any data waiting to be read before sending the request
            self._transport.serial.reset_output_buffer()
            self._transport.serial.reset_input_buffer()
            while not self._q.empty():
                self._q.get_nowait()

            # send the request
            LOG.debug(f"Sending {self._serial_port_path}: %s", request)
            self._transport.write(request)
            self._last_send = time.time()

        #@ensure_connected
        #@locked_method
        async def read(self):
            data = bytearray()
            eol = self._config[CONF_EOL].encode(ASCII)

            # read the response
            try:
                while True:
                    data += await asyncio.wait_for(self._q.get(), self._timeout, loop=self._loop)
                    if eol in data:
                        # only return the first line (ignore all other lines)
                        result_lines = data.split(eol)
                        if len(result_lines) > 1 and result_lines[1]:
                            LOG.debug("Multiple response lines, ignore all but the first: %s", result_lines)

                        result = result_lines[0].decode(ASCII)
                        LOG.debug(f"Read {self._serial_port_path}: %s", result)
                        return result

            except asyncio.TimeoutError:
                # log up to two times within a 5 minute period to avoid saturating the logs
                @limits(calls=2, period=FIVE_MINUTES)
                def log_timeout():
                    LOG.warning(f"Timeout receiving response, ignoring partial data: {data}")
                log_timeout()
                return None


    LOG.debug(f"Connecting to {serial_port_path}: {serial_config}")
    factory = functools.partial(RS232ControlProtocol, serial_port_path, protocol_config, loop)
    _, protocol = await create_serial_connection(loop, factory, serial_port_path, **serial_config)
    return protocol
