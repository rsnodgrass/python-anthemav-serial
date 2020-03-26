#!/usr/local/bin/python3

import os
import pprint
import argparse
import asyncio
import logging
import sys

from anthemav_serial import get_async_amp_controller

#### Logging
root = logging.getLogger()
root.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)
####

parser = argparse.ArgumentParser(description='Anthem RS232 client example')
parser.add_argument('--tty', help='/dev/tty to use (e.g. /dev/tty.usbserial-A501SGSZ)')
args = parser.parse_args()

pp = pprint.PrettyPrinter(indent=4)

async def main(loop):
    series = 'd2v'
    amp = await get_async_amp_controller(series, args.tty, loop)
    pp.pprint(amp)

    zone = 1
    await amp.set_power(zone, True)

    # show amp status
    result = await amp.zone_status(zone)
    pp.pprint(result)


loop = asyncio.get_event_loop()
loop.run_until_complete( main(loop) )
