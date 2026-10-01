"""Threshold alerting, evaluated on the logger side (one place, always running).

Design points from the plan:
  - SPIKE-flagged samples (the ~180 A relay transients) are excluded from
    power/current thresholds -- they are known-false.
  - Debounce: an alert is raised only on the *transition into* a breach that
    persists for >= MIN_BREACH_SAMPLES consecutive samples, so a single noisy
    reading does not spam alerts.
  - Every alert is recorded in the DB; raising also logs and beeps (stdlib only).
"""

import logging
import math
import sys

from . import protocol

log = logging.getLogger("powerprofiler.alerts")

MIN_BREACH_SAMPLES = 2


class _DeviceAlertState:
    __slots__ = ("breach_counts", "active")

    def __init__(self):
        self.breach_counts = {}   # kind -> consecutive breach count
        self.active = set()       # kinds currently in a raised state


class AlertEngine:
    def __init__(self, config, beep=True):
        # Map device name -> thresholds; resolved to device_id lazily.
        self._thresholds_by_name = {d.name: d.alerts for d in config.devices}
        self._names_by_id = {}
        self._state = {}
        self.beep = beep

    def register(self, device_id, name):
        self._names_by_id[device_id] = name
        self._state[device_id] = _DeviceAlertState()

    def evaluate(self, writer, device_id, sample):
        name = self._names_by_id.get(device_id)
        if name is None:
            return
        thr = self._thresholds_by_name.get(name, {})
        if not thr:
            return
        st = self._state[device_id]
        flags = sample["flags"]
        is_spike = bool(flags & protocol.FLAG_SPIKE)

        checks = []
        power = sample["power_w"]
        volt = sample["voltage_v"]
        if "power_w_max" in thr and power is not None and not is_spike:
            checks.append(("power_w_max", power > thr["power_w_max"], power, thr["power_w_max"]))
        if "voltage_v_max" in thr and volt is not None:
            checks.append(("voltage_v_max", volt > thr["voltage_v_max"], volt, thr["voltage_v_max"]))
        if "voltage_v_min" in thr and volt is not None:
            checks.append(("voltage_v_min", volt < thr["voltage_v_min"], volt, thr["voltage_v_min"]))

        for kind, breached, value, limit in checks:
            if breached:
                st.breach_counts[kind] = st.breach_counts.get(kind, 0) + 1
                if (st.breach_counts[kind] >= MIN_BREACH_SAMPLES
                        and kind not in st.active):
                    st.active.add(kind)
                    self._raise(writer, device_id, name, kind, value, limit)
            else:
                st.breach_counts[kind] = 0
                st.active.discard(kind)

    def _raise(self, writer, device_id, name, kind, value, limit):
        msg = "%s %s=%.3f crossed %.3f" % (name, kind, value, limit)
        writer.record_alert(device_id, kind, value, limit, msg)
        log.warning("ALERT: %s", msg)
        if self.beep and sys.platform == "win32":
            try:
                import winsound
                winsound.Beep(880, 150)
            except Exception:
                pass
