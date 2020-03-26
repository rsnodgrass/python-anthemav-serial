#!/usr/local/bin/python3

import os
import sys
import pprint
import argparse
import asyncio
import logging

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
parser.add_argument('--series', default='d2v', help='Anthem amplifier series to test')
parser.add_argument('--tty', help='/dev/tty to use (e.g. /dev/tty.usbserial-A501SGSZ)')
parser.add_argument('--baud', help='baud rate')
args = parser.parse_args()

pp = pprint.PrettyPrinter(indent=4)

config = {}
if args.baud:
    config['baudrate'] = args.baud


async def main(loop):
    amp = await get_async_amp_controller(args.series, args.tty, loop, serial_config_overrides=config)
    pp.pprint(amp)

    await amp.set_power(2, True)

    # show amp status
    for zone in range(1, 4):
        result = await amp.zone_status(zone)
        pp.pprint(result)

        await amp.set_power(zone, False)


loop = asyncio.get_event_loop()
loop.run_until_complete( main(loop) )
