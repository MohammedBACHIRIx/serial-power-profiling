"""Pure, side-effect-free protocol handling for the ISW8001 wattmeter.

Everything here is testable with no hardware: feed canned bytes/lines and
assert on the results. Serial I/O lives in device.py.

ISW8001 wire behavior (see docs/ISW8001-PROTOCOL.md):
  - 9600 8N1, XON/XOFF software flow control.
  - The device embeds XON (0x11) / XOFF (0x13) bytes *inside* the data stream;
    they must be stripped before parsing.
  - Lines are terminated by CR (0x0D); LF (0x0A) may also appear and is ignored.
  - Measurement line example:
        U3=238.5E+0 I1=0.3E-3 W=0.02E+0 PF=0.95E+0
    The U/I prefix carries the active range (calibre) number. Power factor can
    be reported as `PF=overflow`.
"""

import math

# --- Range (calibre) label tables, mirrored from isw8001.js --------------
VOLTAGE_RANGES = {"U1": "50V", "U2": "150V", "U3": "500V"}
CURRENT_RANGES = {"I1": "160mA", "I2": "1.6A", "I3": "16A"}

# Highest real current range is 16 A; anything well above that is a relay
# switching transient (the known ~180 A impossible reading), not real.
SPIKE_CURRENT_A = 20.0

# --- Sample flags (stored, never used to silently drop data) -------------
FLAG_SPIKE = 1 << 0        # impossible current -> range-change relay transient
FLAG_DIP = 1 << 1          # candidate for the "every 500 samples" dip artifact
FLAG_OVERFLOW = 1 << 2     # a quantity came back as `overflow`
FLAG_RECONNECT = 1 << 3    # first sample after a (re)connect

DIP_PERIOD = 500           # the device dips roughly every 500 samples


class ByteFramer:
    """Reassemble CR-terminated ASCII lines from a byte-at-a-time stream.

    Stateful: the device transmits one byte at a time, so partial lines are
    buffered across feed() calls. XON/XOFF and LF are filtered here.
    """

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        """Feed raw bytes; return a list of complete decoded lines (may be empty)."""
        lines = []
        for b in data:
            if b in (0x11, 0x13):      # XON / XOFF embedded in data
                continue
            if b == 0x0D:              # CR -> end of line
                line = self._buf.decode("ascii", errors="ignore").strip()
                self._buf.clear()
                if line:
                    lines.append(line)
            elif b != 0x0A:            # ignore LF, keep everything else
                self._buf.append(b)
        return lines

    def reset(self):
        self._buf.clear()


def _to_float(token):
    """Parse a value token. Returns (float, is_overflow)."""
    low = token.lower()
    if low == "overflow":
        return float("nan"), True
    try:
        return float(token), False
    except ValueError:
        return float("nan"), False


def parse_measurement(line):
    """Parse one measurement line into a normalized dict.

    Returns a dict with keys: voltage, current, power, var, pf (floats, NaN if
    absent/overflow), voltage_range, current_range (label strings or None),
    overflow (bool), and raw (the original line). The ISW8001 always transmits
    voltage and current with their range prefix even when they are not the
    selected function, so U*/I* keys are expected on most lines.
    """
    out = {
        "voltage": float("nan"),
        "current": float("nan"),
        "power": float("nan"),
        "var": float("nan"),
        "pf": float("nan"),
        "voltage_range": None,
        "current_range": None,
        "overflow": False,
        "raw": line,
    }

    for part in line.split():
        if "=" not in part:
            continue
        key, val_str = part.split("=", 1)
        val, is_ovf = _to_float(val_str)
        if is_ovf:
            out["overflow"] = True

        if key in VOLTAGE_RANGES:
            out["voltage"] = val
            out["voltage_range"] = VOLTAGE_RANGES[key]
        elif key in CURRENT_RANGES:
            out["current"] = val
            out["current_range"] = CURRENT_RANGES[key]
        elif key in ("V", "VOLT"):
            out["voltage"] = val
        elif key in ("A", "AMP"):
            out["current"] = val
        elif key in ("W", "WATT"):
            out["power"] = val
        elif key in ("VAR",):
            out["var"] = val
        elif key in ("PF", "PWF", "COS"):
            out["pf"] = val

    return out


def classify_sample(parsed, index):
    """Return a flags bitmask for a parsed sample.

    `index` is the device's running sample counter (0-based). Flags are stored
    alongside the sample so consumers (charts, alerts, export) can filter known
    artifacts without the capture path ever discarding data.
    """
    flags = 0
    cur = parsed.get("current", float("nan"))
    if not math.isnan(cur) and abs(cur) > SPIKE_CURRENT_A:
        flags |= FLAG_SPIKE
    if index > 0 and index % DIP_PERIOD == 0:
        flags |= FLAG_DIP
    if parsed.get("overflow"):
        flags |= FLAG_OVERFLOW
    return flags
