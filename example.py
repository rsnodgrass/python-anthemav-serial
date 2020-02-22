#!/usr/local/bin/python3

import os
import argparse

from anthemav_serial import get_amp_controller, ANTHEM_D2

parser = argparse.ArgumentParser(description=console.__doc__)
parser.add_argument('--tty', default='/dev/tty.usbserial-A501SGSZ', help='/dev/tty to use')
args = parser.parse_args()

amp = get_amp_controller(ANTHEM_D2, args.tty)
print(amp)

amp.set_power(1, True)
amp.set_source(1, 6)
