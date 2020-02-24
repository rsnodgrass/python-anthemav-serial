#!/usr/local/bin/python3

import os
import pprint
import argparse

from anthemav_serial import get_amp_controller, ANTHEM_D2

parser = argparse.ArgumentParser(description='Anthem RS232 client example')
parser.add_argument('--tty', help='/dev/tty to use (e.g. /dev/tty.usbserial-A501SGSZ)')
args = parser.parse_args()

pp = pprint.PrettyPrinter(indent=4)

amp = get_amp_controller(ANTHEM_D2, args.tty)
pp.pprint(amp)

# show amp status
result = amp.get_status()
pp.pprint(result)

zone = 1
amp.set_power(zone, True)
amp.set_source(zone, 6)

# show updated status
result = amp.get_status()
pp.pprint(result)