"""Configuration: load/validate/save the JSON device map and thresholds.

JSON (stdlib) is used deliberately -- no third-party dependency, and unlike
tomllib it is read/write on every supported Python. See config/devices.example.json.
"""

import json
import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


@dataclass
class DeviceConfig:
    name: str
    role: str = "standalone"
    pair: str = None
    port: str = None
    hwid_hint: str = None
    baud: int = 9600
    model: str = "ISW8001"          # or "Demo"
    transport: str = "serial"       # "serial", "tcp" (e.g. WIZ750SR), or "demo"
    tcp_host: str = None
    tcp_port: int = 5000
    function: str = "WATT"
    auto_mode: bool = True
    autorange: bool = True
    alerts: dict = field(default_factory=dict)


@dataclass
class AppConfig:
    db_path: str
    sample_batch_ms: int = 250
    devices: list = field(default_factory=list)


def _as_device(d):
    if "name" not in d or not d["name"]:
        raise ConfigError("every device needs a non-empty 'name'")
    init = d.get("init", {})
    model = d.get("model", "ISW8001")
    transport = d.get("transport")
    if not transport:
        if model == "Demo":
            transport = "demo"
        elif d.get("tcp_host"):
            transport = "tcp"
        else:
            transport = "serial"

    return DeviceConfig(
        name=d["name"],
        role=d.get("role", "standalone"),
        pair=d.get("pair"),
        port=d.get("port"),
        hwid_hint=d.get("hwid_hint"),
        baud=int(d.get("baud", 9600)),
        model=model,
        transport=transport,
        tcp_host=d.get("tcp_host"),
        tcp_port=int(d.get("tcp_port", 5000)),
        function=init.get("function", "WATT"),
        auto_mode=bool(init.get("auto_mode", True)),
        autorange=bool(init.get("auto_range", init.get("autorange", True))),
        alerts=d.get("alerts", {}),
    )


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if "db_path" not in raw:
        from . import storage
        raw["db_path"] = storage.default_db_path()
    devices = [_as_device(d) for d in raw.get("devices", [])]

    seen = set()
    for d in devices:
        if d.name in seen:
            raise ConfigError("duplicate device name: %s" % d.name)
        seen.add(d.name)
        if d.transport == "serial" and not d.port:
            raise ConfigError("serial device %s needs a 'port'" % d.name)
        elif d.transport == "tcp" and not d.tcp_host:
            raise ConfigError("tcp device %s needs 'tcp_host'" % d.name)
    if not devices:
        raise ConfigError("config has no devices")

    cfg = AppConfig(
        db_path=os.path.expandvars(raw["db_path"]),
        sample_batch_ms=int(raw.get("sample_batch_ms", 250)),
        devices=devices,
    )
    return cfg


def save(cfg, path):
    data = {
        "db_path": cfg.db_path,
        "sample_batch_ms": cfg.sample_batch_ms,
        "devices": [{
            "name": d.name, "role": d.role, "pair": d.pair, "port": d.port,
            "hwid_hint": d.hwid_hint, "baud": d.baud, "model": d.model,
            "transport": d.transport, "tcp_host": d.tcp_host, "tcp_port": d.tcp_port,
            "init": {"function": d.function, "auto_mode": d.auto_mode,
                     "autorange": d.autorange},
            "alerts": d.alerts,
        } for d in cfg.devices],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
