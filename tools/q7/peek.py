"""Read values from the unpacked image by symbol name.

usage: peek.py firmware.bin image.bin NAME[:fmt[:count]] ...     fmt: h H i I b B (default h)
"""
import struct, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import symbols as S

BASE = 0x80000600

class Image:
    def __init__(self, firmware, image):
        self.data = open(firmware, "rb").read()
        self.memory = open(image, "rb").read()
        self.symbols = S.load(self.data)
        self.size = S.sizes(self.symbols)
        self.address = {}
        for address, name in self.symbols:
            self.address.setdefault(name, address)
        self.names = {}
        for address, name in self.symbols:
            self.names.setdefault(address, name)

    def read(self, address, fmt, count):
        return struct.unpack_from(f"<{count}{fmt}", self.memory, address - BASE)

    def values(self, name, fmt="h", count=None):
        address = self.address[name]
        if count is None:
            count = self.size[address] // struct.calcsize(fmt)
        return self.read(address, fmt, count)

if __name__ == "__main__":
    image = Image(sys.argv[1], sys.argv[2])
    for spec in sys.argv[3:]:
        parts = spec.split(":")
        name, fmt, count = parts[0], (parts[1] if len(parts) > 1 else "h"), (parts[2] if len(parts) > 2 else None)
        values = image.values(name, fmt or "h", int(count) if count else None)
        print(f"{name} @ {image.address[name]:#x} ({len(values)} x {fmt}):")
        for i in range(0, len(values), 9 if len(values) % 9 == 0 or len(values) == 10 else 16):
            step = 9 if len(values) % 9 == 0 or len(values) == 10 else 16
            print("   " + " ".join(f"{v:6d}" for v in values[i:i + step]))
