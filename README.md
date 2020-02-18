# Python RS232 API for Anthem Pre-Amplifiers

Library for controlling Anthem pre-amplifiers (e.g. Statement D2) via RS232 serial connections.

#### Supported Anthem Pre-Amps

|  Model(s)                  | Type Code    | Notes |
|  ------------------------- | ------------ | ----- |
|  Statement D2, D2v, D2v 3D | ANTHEM_D2    | |
|  Statement D1              | ANTHEM_D1    | |
|  AVM 50 / AVM 60           |              | unknown |
|  AVM 30                    | ANTHEM_AVM30 | |
|  AVM 20                    | ANTHEM_AVM20 | |
|  MRX 500                   |              | unknown if supported |

## Usage

```python
from pyanthem import get_amp_controller, ANTHEM_D2

type_code = ANTHEM_D2
amp = get_amp_controller(type_code, '/dev/ttyUSB0')
amp.mute_on(1)
```

See also [example.py](example.py) for a more complete example.

## Usage with asyncio

With the `asyncio` flavor, all methods of the controller objects are coroutines:

```python
import asyncio
from pyanthem import get_async_amp_controller, ANTHEM_D2

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

Details on RS232 protocol:

* [AVM 2 Serial Programming](https://www.avsforum.com/forum/26-home-theater-computers/188206-rs232-control-avm-2-help.html#post1521446)
* [Serial commands and feedback from Anthem pre/pro](http://allonis.com/forum/viewtopic.php?t=2185)
* http://www.remotecentral.com/cgi-bin/mboard/rc-touch/thread.cgi?2525
* https://www.anthemav.com/downloads/Anthem%203-zone%20AVP%20serial%20commands.zip
