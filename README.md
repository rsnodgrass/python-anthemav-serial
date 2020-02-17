# Python RS232 API for Anthem Pre-Amplifiers

Library for communicating via RS232 serial to them Anthem Statement D2 pre-amp. This may work with other Anthem pre-amplifiers, but this has not been tested with them.

## Usage

```python
from pyanthem import get_amp_controller, ANTHEM_D2

amp = get_amp_controller(ANTHEM_D2, '/dev/ttyUSB0')
amp.
```

See also [example.py](example.py) for a more complete example.

## Usage with asyncio

With the `asyncio` flavor, all methods of the controller objects are coroutines:

```python
import asyncio
from pyanthem import get_async_amp_controller, ANTHEM_D2

async def main(loop):
    amp = await get_async_amp_controller(ANTHEM_D2, '/dev/ttyUSB0', loop)
    zone_status = await amp.zone_status(11)
    if zone_status.power:
        await amp.set_power(zone_status.zone, False)

loop = asyncio.get_event_loop()
loop.run_until_complete(main(loop))
```

## Supported Anthem Pre-Amps

|  Model(s)                  | Type Code    | Notes |
|  ------------------------- | ------------ | ----- |
|  Statement D2, D2v, D2v 3D | ANTHEM_D2    | |
|  Statement D1              | ANTHEM_D1    | |
|  AVM 30                    | ANTHEM_AVM30 | |
|  AVM 20                    | ANTHEM_AVM20 | |
|  MRX 500                   |              | unknown if supported |

## See Also

* [Anthem D2/D2v/AVM50/AVM50v/ARC1 tweaking guide (AVS Forum)](https://www.avsforum.com/forum/90-receivers-amps-processors/678260-anthem-d2-d2v-avm50-avm50v-arc1-tweaking-guide-1510.html)
