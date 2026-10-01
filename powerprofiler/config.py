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
    return DeviceConfig(
        name=d["name"],
        role=d.get("role", "standalone"),
        pair=d.get("pair"),
        port=d.get("port"),
        hwid_hint=d.get("hwid_hint"),
        baud=int(d.get("baud", 9600)),
        model=d.get("model", "ISW8001"),
        function=init.get("function", "WATT"),
        auto_mode=bool(init.get("auto_mode", True)),
        autorange=bool(init.get("autorange", True)),
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
        if d.model != "Demo" and not d.port:
            raise ConfigError("device %s needs a 'port' (or model 'Demo')" % d.name)
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
            "init": {"function": d.function, "auto_mode": d.auto_mode,
                     "autorange": d.autorange},
            "alerts": d.alerts,
        } for d in cfg.devices],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
