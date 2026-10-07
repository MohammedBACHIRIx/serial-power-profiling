"""DeviceWorker: one thread owning one serial port (or demo transport).

Each worker is fully isolated: all serial I/O is wrapped in try/except, and a
failure only affects that worker, which then reconnects with exponential
backoff. Workers never touch the database directly -- they emit messages
(samples and health transitions) onto a shared outbound queue drained by the
logger's single writer thread, and receive device commands on an inbound queue.
"""

import math
import threading
import time

from . import protocol

# Health states
CONNECTING = "CONNECTING"
HEALTHY = "HEALTHY"
STALE = "STALE"
DISCONNECTED = "DISCONNECTED"
ERROR = "ERROR"

_CR = b"\r"


class SerialTransport:
    """Thin wrapper over serial.Serial with hwid-based port recovery."""

    def __init__(self, port, baud=9600, hwid_hint=None):
        self.port = port
        self.baud = baud
        self.hwid_hint = hwid_hint
        self._ser = None
        self.is_open = False

    def resolve_port(self):
        """If the configured port is gone, find it by hwid (PL-2303 renumbering).

        Returns the port name to use; may differ from the original after a
        USB replug reassigns COM numbers.
        """
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        names = {p.device for p in ports}
        if self.port in names:
            return self.port
        if self.hwid_hint:
            hint = self.hwid_hint.lower()
            for p in ports:
                hay = ("%s %s %s" % (p.hwid or "", p.serial_number or "",
                                     p.description or "")).lower()
                if hint in hay or (p.serial_number and p.serial_number.lower() in hint):
                    self.port = p.device
                    return p.device
        return self.port

    def open(self):
        import serial
        name = self.resolve_port()
        self._ser = serial.Serial(name, self.baud, timeout=0.1, xonxoff=True)
        self.port = name
        self.is_open = True

    def close(self):
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        finally:
            self._ser = None
            self.is_open = False

    def write(self, data):
        if self._ser and self._ser.is_open:
            self._ser.write(data)

    def read(self):
        if not (self._ser and self._ser.is_open):
            return b""
        n = self._ser.in_waiting
        if n:
            return self._ser.read(n)
        time.sleep(0.01)
        return b""


class TcpTransport:
    """Socket-based transport for Ethernet-to-Serial modules (e.g. WIZ750SR, Moxa, ESP-link)."""

    def __init__(self, host, port=5000, timeout=3.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._sock = None
        self.is_open = False

    def resolve_port(self):
        return f"{self.host}:{self.port}"

    def open(self):
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self.host, self.port))
        sock.settimeout(0.02)
        self._sock = sock
        self.is_open = True

    def close(self):
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None
            self.is_open = False

    def write(self, data):
        if self._sock and self.is_open:
            self._sock.sendall(data)

    def read(self):
        import socket
        if not (self._sock and self.is_open):
            return b""
        try:
            return self._sock.recv(1024)
        except (socket.timeout, BlockingIOError):
            time.sleep(0.01)
            return b""


class DeviceWorker(threading.Thread):
    def __init__(self, device_id, name, transport, out_queue, cmd_queue,
                 init_commands=("WATT", "MA1"), stale_seconds=3.0):
        super().__init__(name="worker-%s" % name, daemon=True)
        self.device_id = device_id
        self.dev_name = name
        self.transport = transport
        self.out_queue = out_queue
        self.cmd_queue = cmd_queue
        self.init_commands = tuple(init_commands)
        self.stale_seconds = stale_seconds

        self._running = False
        self._framer = protocol.ByteFramer()
        self._index = 0
        self._energy_wh = 0.0
        self._last_power = None
        self._last_sample_ts = None
        self._pending_reconnect_flag = False
        self._state = None
        self._stale_recovered = False

    # -- messaging ---------------------------------------------------------
    def _emit_sample(self, parsed, flags, ts):
        self.out_queue.put(("sample", self.device_id, {
            "ts": ts,
            "power_w": _nan_to_none(parsed["power"]),
            "voltage_v": _nan_to_none(parsed["voltage"]),
            "current_a": _nan_to_none(parsed["current"]),
            "pf": _nan_to_none(parsed["pf"]),
            "var_var": _nan_to_none(parsed["var"]),
            "energy_wh": self._energy_wh,
            "v_range": parsed["voltage_range"],
            "i_range": parsed["current_range"],
            "flags": flags,
            "parsed": parsed,
        }))

    def _set_state(self, state, detail=None):
        if state != self._state:
            self._state = state
            self.out_queue.put(("health", self.device_id, {
                "state": state, "detail": detail, "com_port": self.transport.port
                if hasattr(self.transport, "port") else None,
            }))

    # -- lifecycle ---------------------------------------------------------
    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        backoff = 0.5
        while self._running:
            if not self.transport.is_open:
                self._set_state(CONNECTING)
                try:
                    self.transport.open()
                    for cmd in self.init_commands:
                        self.transport.write(cmd.encode("ascii") + _CR)
                    backoff = 0.5
                    self._pending_reconnect_flag = True
                    self._stale_recovered = False
                    self._set_state(HEALTHY, "connected")
                except Exception as e:  # noqa: BLE001 - isolate all failures
                    self._set_state(DISCONNECTED, str(e))
                    self.transport.close()
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 10.0)
                    continue

            try:
                self._drain_commands()
                data = self.transport.read()
                if data:
                    for line in self._framer.feed(data):
                        self._process_line(line)
                self._check_stale()
            except Exception as e:  # noqa: BLE001 - isolate all failures
                self._set_state(ERROR, str(e))
                self.transport.close()
                self._framer.reset()
                time.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

        self.transport.close()
        self._set_state(DISCONNECTED, "stopped")

    def _drain_commands(self):
        while True:
            try:
                cmd = self.cmd_queue.get_nowait()
            except Exception:
                break
            if cmd:
                self.transport.write(cmd.encode("ascii") + _CR)

    def _process_line(self, line):
        now = time.time()
        parsed = protocol.parse_measurement(line)
        flags = protocol.classify_sample(parsed, self._index)
        if self._pending_reconnect_flag:
            flags |= protocol.FLAG_RECONNECT
            self._pending_reconnect_flag = False
        self._index += 1

        # Energy integral: power * dt, only when we have real consecutive power.
        w = parsed["power"]
        if not math.isnan(w):
            if self._last_sample_ts is not None:
                dt_h = (now - self._last_sample_ts) / 3600.0
                if 0 < dt_h < 1.0:  # guard against clock jumps / long gaps
                    self._energy_wh += w * dt_h
            self._last_power = w

        self._last_sample_ts = now
        self._stale_recovered = False
        self._set_state(HEALTHY)
        self._emit_sample(parsed, flags, now)

    def _check_stale(self):
        if self._last_sample_ts is None:
            return
        gap = time.time() - self._last_sample_ts
        if gap > self.stale_seconds:
            if not self._stale_recovered:
                # First escalation: re-arm auto emission (device may have
                # dropped MA1 across a glitch), then wait one more interval.
                self._set_state(STALE, "no data for %.1fs" % gap)
                try:
                    self.transport.write(b"MA1" + _CR)
                except Exception:
                    pass
                self._stale_recovered = True
            elif gap > self.stale_seconds * 2:
                # Still nothing -> force a full reconnect.
                raise OSError("stale: no data for %.1fs" % gap)


def _nan_to_none(x):
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x
