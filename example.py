#!/usr/local/bin/python3

import os
import pprint
import argparse

from anthemav_serial import get_amp_controller

parser = argparse.ArgumentParser(description='Anthem RS232 client example')
parser.add_argument('--tty', help='/dev/tty to use (e.g. /dev/tty.usbserial-A501SGSZ)')
parser.add_argument('--baud', help='baud rate')
args = parser.parse_args()

pp = pprint.PrettyPrinter(indent=4)

config = {
    'rs232': {
        'baudrate': args.baud
    }
}

series = 'd2v'
amp = get_amp_controller(series, args.tty, config)
pp.pprint(amp)

zone = 1

# show amp status
result = amp.zone_status(zone)
pp.pprint(result)

amp.set_power(zone, True)
amp.set_source(zone, 6)

# show updated status
result = amp.zone_status(zone)
pp.pprint(result)
