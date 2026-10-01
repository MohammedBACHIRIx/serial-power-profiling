"""Synthetic ISW8001 source for hardware-free testing.

DemoTransport mimics the serial interface used by device.DeviceWorker: it
emits ISW8001-style measurement lines (with embedded XON/XOFF, occasional
range-change current spikes, and the periodic dip) at roughly the real device
cadence, so the whole pipeline can be exercised with no COM ports attached.
"""

import math
import random
import time


class DemoTransport:
    """A fake serial transport producing realistic ISW8001 lines.

    Interface mirrors SerialTransport: open/close/write/read/resolve_port and
    an `is_open` attribute. `read()` returns raw bytes (CR-terminated, with the
    occasional embedded XON/XOFF byte the real device injects).
    """

    def __init__(self, name="demo", phase=0.0, base_w=50.0, voltage=230.0,
                 interval=0.47, inject_fault_after=None):
        self.name = name
        self.phase = phase
        self.base_w = base_w
        self.voltage = voltage
        self.interval = interval
        self.inject_fault_after = inject_fault_after
        self.is_open = False
        self._t0 = None
        self._next = 0.0
        self._count = 0
        self.last_command = None

    def resolve_port(self):
        return self.name

    def open(self):
        self.is_open = True
        self._t0 = time.time()
        self._next = self._t0 + self.interval

    def close(self):
        self.is_open = False

    def write(self, data):
        self.last_command = bytes(data).decode("ascii", "ignore").strip()

    def read(self):
        now = time.time()
        if not self.is_open or now < self._next:
            return b""
        self._next = now + self.interval
        self._count += 1

        if self.inject_fault_after and self._count > self.inject_fault_after:
            raise OSError("demo device %s simulated disconnect" % self.name)

        t = now - self._t0 + self.phase
        w = self.base_w + math.sin(t) * 10.0 + random.random() * 2.0
        v = self.voltage + math.sin(t * 0.1) * 2.0
        i = w / v if v else 0.0

        # Every 500th sample reproduce the device's known dip artifact.
        if self._count % 500 == 0:
            w *= 0.1
        # Occasionally inject an impossible range-change current spike.
        spike = (random.random() < 0.002)
        if spike:
            i = 180.0

        pf = 0.95 + random.random() * 0.04
        line = "U3=%.1fE+0 I2=%.4fE+0 W=%.3fE+0 PF=%.2fE+0" % (v, i, w, pf)
        # Inject XON/XOFF mid-line, exactly as the hardware does.
        raw = line.encode("ascii")
        mid = len(raw) // 2
        raw = raw[:mid] + b"\x11" + raw[mid:] + b"\x13\r"
        return raw
