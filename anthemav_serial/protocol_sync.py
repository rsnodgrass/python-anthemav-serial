"""Simple RS232 communication mechanism for request/reply style commands"""

import logging

import serial
import time

from .const import ASCII, CONF_EOL, CONF_THROTTLE_RATE, CONF_TIMEOUT, DEFAULT_TIMEOUT, FIVE_MINUTES

LOG = logging.getLogger(__name__)

async def get_sync_rs232_protocol(serial_port_path, serial_config, communication_config):

    class RS232SyncProtocol():
        def __init__(self, serial_port_path, serial_config, communication_config):
            self._serial_port_path = serial_port_path
            self._config = communication_config

            # FIXME: ensure there is an EOL defined

            self._timeout = self._config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            self._last_send = time.time() - self._timeout

            self._port = serial.serial_for_url(serial_port_path, **serial_config)
            LOG.debug(f"RS232SyncProtocol initialized {serial_port_path}: {serial_config}")

        def send(self, request: bytes, skip=0):
            """
            :param request: request that is sent to the RS232 connected device
            :param skip: number of bytes to skip for end of transmission decoding
            """
            self._apply_request_throttling()

            port = self._port
            port.reset_output_buffer()
            port.reset_input_buffer()

            LOG.debug(f'Sending: %s', request)
            port.write(request)
            port.flush()

        def read(self):
            eol = self._config[CONF_EOL].encode(ASCII)
            len_eol = len(eol)

            result = bytearray()
            while True:
                c = self._port.read(1)
                if not c:
                    ret = bytes(result)
                    LOG.info("Received partial: %s", result)
                    raise serial.SerialTimeoutException(
                        'Connection timed out! Last received bytes {}'.format([hex(a) for a in result]))
                result += c
                if len(result) > skip and result[-len_eol:] == eol:
                    break

            ret = bytes(result)
            LOG.debug('Received: %s', ret)
            return ret.decode(ASCII)

        def delay_requests(self, seconds: float):
            """Throttle future requests for at least the specific seconds since last request"""
            delta_since_last_send = time.time() - self._last_send
            self._last_send = (time.time() - delta_since_last_send) + seconds

        # throttle the number of RS232 sends per second to avoid causing timeouts
        def _apply_request_throttling(self):
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
                await time.sleep(delay)


    LOG.debug(f"Connecting to {serial_port_path}: {serial_config} {communication_config}")
    return RS232SyncProtocol(serial_port_path, serial_config, communication_config)