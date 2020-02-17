#!/usr/local/bin/python3

from pyanthem import get_amp_controller, ANTHEM_D2

amp = get_amp_controller(ANTHEM_D2, '/dev/tty.usbserial-A501SGSZ')

amp.mute_on(1)
