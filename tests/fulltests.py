#!/usr/bin/env python3

import asyncio
import logging


async def test():
    log = logging.getLogger(__name__)

    def log_callback(message):
        log.info("Callback invoked: %s" % message)

    tty = "/dev/tty.usb-serial"

    log.info("Connecting to Anthem AVR at %s" % (tty))

    # conn = await anthemav.Connection.create(host=host,port=port,loop=loop,update_callback=log_callback,auto_reconnect=False)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test())
