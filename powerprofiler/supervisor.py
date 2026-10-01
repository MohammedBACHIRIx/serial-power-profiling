"""DeviceSupervisor: owns N DeviceWorkers and the single DB writer thread.

Threading model:
  - One DeviceWorker thread per device (serial I/O, fully isolated).
  - One writer thread (this class's _writer_loop) that is the *only* thing
    touching the SQLite write connection: it drains the workers' outbound
    queue, batches sample inserts, records health transitions, evaluates
    alerts, and dispatches queued GUI commands back to the workers.

A failing or unplugged device cannot stall the others or the writer: workers
communicate only through the thread-safe queue, and the writer never blocks on
any single device.
"""

import queue
import threading
import time

from . import device as dev_mod
from . import storage


class DeviceSupervisor:
    def __init__(self, config, writer, alert_engine=None):
        self.config = config
        self.writer = writer
        self.alert_engine = alert_engine
        self.out_queue = queue.Queue(maxsize=10000)
        self.workers = {}          # device_id -> DeviceWorker
        self.cmd_queues = {}       # device_id -> queue.Queue
        self._writer_thread = None
        self._running = False

    def build(self, transport_factory):
        """Register devices and create workers.

        transport_factory(device_cfg) -> transport object (SerialTransport or
        DemoTransport). This indirection lets tests inject demo transports.
        """
        for dcfg in self.config.devices:
            device_id = self.writer.get_or_create_device(
                dcfg.name, role=dcfg.role, com_hint=dcfg.port, hwid=dcfg.hwid_hint)
            cmd_q = queue.Queue()
            transport = transport_factory(dcfg)
            init = []
            if dcfg.function:
                init.append(dcfg.function)
            if dcfg.auto_mode:
                init.append("MA1")
            if dcfg.autorange:
                init.append("AUTORANGE")
            worker = dev_mod.DeviceWorker(
                device_id, dcfg.name, transport, self.out_queue, cmd_q,
                init_commands=tuple(init) or ("WATT", "MA1"),
                stale_seconds=dcfg.alerts.get("stale_seconds", 3.0),
            )
            self.workers[device_id] = worker
            self.cmd_queues[device_id] = cmd_q

    def start(self):
        self._running = True
        self.writer.start_session("auto")
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="db-writer", daemon=True)
        self._writer_thread.start()
        for w in self.workers.values():
            w.start()

    def stop(self):
        self._running = False
        for w in self.workers.values():
            w.stop()
        if self._writer_thread:
            self._writer_thread.join(timeout=5.0)
        self.writer.end_session()

    # -- the single writer loop -------------------------------------------
    def _writer_loop(self):
        last_flush = time.time()
        last_cmd_poll = 0.0
        last_checkpoint = time.time()
        batch_s = max(self.config.sample_batch_ms, 50) / 1000.0

        while self._running or not self.out_queue.empty():
            try:
                kind, device_id, payload = self.out_queue.get(timeout=0.1)
            except queue.Empty:
                kind = None

            if kind == "sample":
                self.writer.enqueue(
                    device_id, payload["ts"], payload["power_w"],
                    payload["voltage_v"], payload["current_a"], payload["pf"],
                    payload["var_var"], payload["energy_wh"], payload["v_range"],
                    payload["i_range"], payload["flags"])
                if self.alert_engine:
                    self.alert_engine.evaluate(self.writer, device_id, payload)
            elif kind == "health":
                self.writer.record_health(
                    device_id, payload["state"], payload["detail"],
                    payload.get("com_port"))

            now = time.time()
            if now - last_flush >= batch_s:
                self.writer.flush()
                last_flush = now
            if now - last_cmd_poll >= 0.5:
                self._dispatch_commands()
                last_cmd_poll = now
            if now - last_checkpoint >= 30.0:
                self.writer.flush()
                self.writer.checkpoint()
                last_checkpoint = now

        self.writer.flush()

    def _dispatch_commands(self):
        for device_id, cmd_q in self.cmd_queues.items():
            for _id, command in self.writer.claim_pending_commands(device_id):
                cmd_q.put(command)
