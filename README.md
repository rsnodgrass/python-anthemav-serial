# Python RS232 API for Anthem Receivers and Pre-Amplifiers

Library for controlling Anthem receivers and pre-amplifiers (e.g. Statement D2) via RS232 serial connections. The structure of this library is based off pymonoprice.

#### Supported Anthem Models

This currently only supports Anthem models which communicate using Anthen's original RS232 serial Gen1 interface. For later models (while the Gen2 serial interface is still unsupported), the [IP-based 'python-anthemav' library for communicating](https://github.com/nugget/python-anthemav) can be used.

|  Model(s)                        | Series | Series Const | RS232 Gen1 | RS232 Gen2 | IP |
|  ------------------------------- | ------ | ------------ |:----------:|:----------:|:--:|
|  Statement D2, D2v, D2v 3D       | d2     | ANTHEM_D2    | X |   |   |
|  Statement D1                    | d1     | ANTHEM_D1    | X |   |   |
|  AVM 20                          | avm20  | ANTHEM_AVM20 | X |   |   |
|  AVM 30                          | avm30  | ANTHEM_AVM30 | X |   |   |
|  AVM 50, AVM 50v                 | avm50  | ANTHEM_AVM50 | X |   |   |
|  MRX 300, MRX 500, MRX 700       | mrx    | ANTHEM_MRX   | X |   |   |
|  AVM 60                          | avm60  | ANTHEM_AVM60 |   | X | X | 
|  MRX 310, MRX 510, MRX 710       | mrx1   | ANTHEM_MRX1  |   | X | X |
|  MRX 520, MRX 720, MRX 1120      | mrx2   | ANTHEM_MRX2  |   | X | X |
|  STR amplifiers                  | str    | ANTHEM_STR   |   | X | X |

The list of series constants are enumerated in the `SUPPORTED_ANTHEM_SERIES` variable.

## Usage

```python
from anthemav_serial import get_amp_controller, ANTHEM_D2

serial_port = '/dev/ttyUSB0'
amp = get_amp_controller(ANTHEM_D2, serial_port)

amp.mute_on(1)
```

See also [example.py](example.py) for a more complete example.

## Usage with asyncio

With the `asyncio` flavor, all methods of the controller objects are coroutines:

```python
import asyncio
from anthemav_serial import get_async_amp_controller, ANTHEM_D2

async def main(loop):
    amp = await get_async_amp_controller(ANTHEM_D2, '/dev/ttyUSB0', loop)
    await amp.set_power(zone, False)

loop = asyncio.get_event_loop()
loop.run_until_complete(main(loop))
```

## Known Issues

* cannot query the existing state of the pre-amps (e.g. current volume, sources, etc)

## See Also

* [Anthem D2/D2v/AVM50/AVM50v/ARC1 tweaking guide (AVS Forum)](https://www.avsforum.com/forum/90-receivers-amps-processors/678260-anthem-d2-d2v-avm50-avm50v-arc1-tweaking-guide-1510.html)
* [Python interface for IP-based Anthem receivers](https://github.com/nugget/python-anthemav)

Details on RS232 protocol:

* [AVM 2 Serial Programming](https://www.avsforum.com/forum/26-home-theater-computers/188206-rs232-control-avm-2-help.html#post1521446)
* [Serial commands and feedback from Anthem pre/pro](http://allonis.com/forum/viewtopic.php?t=2185)
* http://www.remotecentral.com/cgi-bin/mboard/rc-touch/thread.cgi?2525
* https://www.anthemav.com/downloads/Anthem%203-zone%20AVP%20serial%20commands.zip