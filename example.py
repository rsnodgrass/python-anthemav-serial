#!/usr/local/bin/python3

import os
import pprint
import argparse

from anthemav_serial import get_amp_controller, ANTHEM_D2

parser = argparse.ArgumentParser(description=console.__doc__)
parser.add_argument('--tty', default='/dev/tty.usbserial-A501SGSZ', help='/dev/tty to use')
args = parser.parse_args()

amp = get_amp_controller(ANTHEM_D2, args.tty)

pp = pprint.PrettyPrinter(indent=4)
pp.print(amp)

# show amp status
result = amp.get_status()
pp.print(result)

zone = 1
amp.set_power(zone, True)
amp.set_source(zone, 6)