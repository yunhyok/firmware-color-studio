"""Name the symbol at or below each address and print the data there.

usage: addr.py firmware.bin image.bin 0xADDR[:fmt[:count]] ...
"""
import bisect, struct, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from peek import Image, BASE

image = Image(sys.argv[1], sys.argv[2])
addresses = sorted(image.names)
for spec in sys.argv[3:]:
    parts = spec.split(":")
    address = int(parts[0], 16)
    fmt = parts[1] if len(parts) > 1 and parts[1] else "h"
    i = bisect.bisect_right(addresses, address) - 1
    base = addresses[i]
    size = image.size.get(base, 0)
    count = int(parts[2]) if len(parts) > 2 else max(1, min(18, (size - (address - base)) // struct.calcsize(fmt)))
    values = image.read(address, fmt, count)
    print(f"{address:#x} = {image.names[base]}+{address - base:#x} (size {size}): " + " ".join(str(v) for v in values))
