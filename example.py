#!/usr/local/bin/python3

import os
from pyanthem import get_amp_controller, ANTHEM_D2

tty = os.getenv('AMP_TTY', None)

#if tty == None:
#    print("ERROR! Must define env variable AMP_TTY (e.g. /dev/ttyUSB1")
#    raise SystemExit

amp = get_amp_controller(ANTHEM_D2, '/dev/tty.usbserial-A501SGSZ')
print(amp)

amp.set_power(1, True)
#amp.mute_on(1)
