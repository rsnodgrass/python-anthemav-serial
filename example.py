#!/usr/local/bin/python3

import os
import sys
import pprint
import argparse
import logging

from anthemav_serial import get_amp_controller

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

amp = get_amp_controller(args.series, args.tty, serial_config_overrides=config)
pp.pprint(amp)

zone = 1

# show amp status
result = amp.zone_status(zone)
pp.pprint(result)

if result['power'] is True:
    print("Amp is initially on!")
elif result['power'] is False:
    print("Amp is initially off!")
else:
    print("Amp power statue is unknown")

amp.set_power(zone, True)
amp.set_source(zone, 6)

# show updated status
result = amp.zone_status(zone)
pp.pprint(result)
