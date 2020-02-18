#!/usr/local/bin/python3

import os
from pyanthem import get_amp_controller, ANTHEM_D2

tty = os.getenv('AMP_TTY', None)

if tty == None:
    print("ERROR! Must define env variable AMP_TTY (e.g. export AMP_TTY=/dev/tty.usbserial-A501SGSZ)")
    raise SystemExit

amp = get_amp_controller(ANTHEM_D2, tty)
print(amp)

amp.set_power(1, True)
amp.set_source(1, 6)
