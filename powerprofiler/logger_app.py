"""Headless logger: reads all configured ISW8001 meters into SQLite.

Run unattended (e.g. via Task Scheduler at logon):
    pythonw scripts/run_logger.pyw
or directly:
    python -m powerprofiler.logger_app --config config/devices.json

No GUI. The tkinter viewer attaches to the same database read-only.
"""

import argparse
import logging
import signal
import sys
import time

from . import alerts, config as config_mod, demo, device, storage, supervisor


def _transport_factory(dcfg):
    if dcfg.model == "Demo":
        return demo.DemoTransport(name=dcfg.name)
    return device.SerialTransport(dcfg.port, baud=dcfg.baud, hwid_hint=dcfg.hwid_hint)


def build_logger(cfg):
    storage.validate_db_path(cfg.db_path)
    writer = storage.Writer(cfg.db_path, batch_ms=cfg.sample_batch_ms)
    engine = alerts.AlertEngine(cfg)
    sup = supervisor.DeviceSupervisor(cfg, writer, alert_engine=engine)
    sup.build(_transport_factory)
    # Wire alert engine to the registered device ids.
    for device_id, worker in sup.workers.items():
        engine.register(device_id, worker.dev_name)
    return writer, sup


def main(argv=None):
    parser = argparse.ArgumentParser(description="ISW8001 headless power logger")
    parser.add_argument("--config", required=True, help="path to devices.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("powerprofiler.logger")

    cfg = config_mod.load(args.config)
    log.info("loaded config: %d device(s), db=%s", len(cfg.devices), cfg.db_path)

    try:
        lock = storage.WriterLock(cfg.db_path).acquire()
    except RuntimeError as e:
        log.error("%s", e)
        return 2

    writer, sup = build_logger(cfg)

    stop = {"flag": False}

    def _handle(signum, frame):
        log.info("signal %s -> shutting down", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle)

    sup.start()
    log.info("logger running; press Ctrl+C to stop")
    try:
        while not stop["flag"]:
            time.sleep(0.5)
    finally:
        sup.stop()
        writer.close()
        lock.release()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
