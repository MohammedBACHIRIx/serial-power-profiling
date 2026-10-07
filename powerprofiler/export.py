import csv
import json
import math
import os
import argparse
from typing import List, Dict, Any
from . import storage

def export_csv(db_path: str, device_id: int, start_ts: float, end_ts: float, out_path: str):
    """Export single-device time series samples to CSV."""
    reader = storage.Reader(db_path)
    try:
        samples = reader.samples_in_range(device_id, start_ts, end_ts)
    finally:
        reader.close()
        
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "ts_iso", "ts_epoch", "power_w", "voltage_v", "current_a", 
            "pf", "var_var", "energy_wh", "v_range", "i_range", "flags"
        ])
        import datetime
        for s in samples:
            ts = s["ts"]
            ts_iso = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
            writer.writerow([
                ts_iso, 
                ts,
                s.get("power_w", ""),
                s.get("voltage_v", ""),
                s.get("current_a", ""),
                s.get("pf", ""),
                s.get("var_var", ""),
                s.get("energy_wh", ""),
                s.get("v_range", ""),
                s.get("i_range", ""),
                s["flags"]
            ])


def export_paired_efficiency_csv(db_path: str, in_device_id: int, out_device_id: int, 
                                start_ts: float, end_ts: float, out_path: str, tolerance_s: float = 1.0):
    """Export time-aligned input/output power, efficiency (%), and losses (W) to CSV."""
    reader = storage.Reader(db_path)
    try:
        in_samples = reader.samples_in_range(in_device_id, start_ts, end_ts)
        out_samples = reader.samples_in_range(out_device_id, start_ts, end_ts)
    finally:
        reader.close()

    import datetime
    out_idx = 0
    num_out = len(out_samples)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "timestamp_iso", "timestamp_epoch",
            "p_in_ac_w", "v_in_ac_v", "i_in_ac_a", "pf_in",
            "p_out_dc_w", "v_out_dc_v", "i_out_dc_a",
            "efficiency_pct", "loss_w"
        ])

        for s_in in in_samples:
            ts = s_in["ts"]
            ts_iso = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
            p_in = s_in.get("power_w")

            # Find closest out_sample in time
            closest_out = None
            min_dt = float("inf")
            while out_idx < num_out:
                dt = abs(out_samples[out_idx]["ts"] - ts)
                if dt < min_dt:
                    min_dt = dt
                    closest_out = out_samples[out_idx]
                if out_samples[out_idx]["ts"] > ts + tolerance_s:
                    break
                out_idx += 1

            p_out = closest_out.get("power_w") if closest_out and min_dt <= tolerance_s else None
            v_out = closest_out.get("voltage_v") if closest_out and min_dt <= tolerance_s else ""
            i_out = closest_out.get("current_a") if closest_out and min_dt <= tolerance_s else ""

            eff = ""
            loss = ""
            if p_in is not None and p_out is not None and p_in > 0:
                eff = round((p_out / p_in) * 100.0, 3)
                loss = round(p_in - p_out, 3)

            writer.writerow([
                ts_iso, ts,
                p_in if p_in is not None else "",
                s_in.get("voltage_v", ""),
                s_in.get("current_a", ""),
                s_in.get("pf", ""),
                p_out if p_out is not None else "",
                v_out, i_out,
                eff, loss
            ])

def _watt_second_to_pico_watt_hour(value: float) -> int:
    if value is None or math.isnan(value):
        return 0
    return round(value / 3600.0 * 1e12)

def _counter_object(name: str, description: str, times: List[int], samples_energy: List[int]) -> Dict:
    time_out = []
    count_out = []
    
    for i in range(len(samples_energy)):
        val = samples_energy[i]
        keep = False
        if val != 0:
            keep = True
        elif i == 0 or i == len(samples_energy) - 1:
            keep = True
        elif samples_energy[i-1] != 0 or samples_energy[i+1] != 0:
            keep = True
            
        if keep:
            time_out.append(times[i])
            count_out.append(val)
            
    return {
        "name": name,
        "category": "power",
        "description": description,
        "pid": "0",
        "mainThreadIndex": 0,
        "samples": {
            "time": time_out,
            "count": count_out,
            "length": len(count_out)
        }
    }

def export_firefox_profile(db_path: str, device_id: int, start_ts: float, end_ts: float, out_path: str):
    reader = storage.Reader(db_path)
    try:
        samples = reader.samples_in_range(device_id, start_ts, end_ts)
        devices = reader.devices()
        device_name = "Unknown"
        for d in devices:
            if d["id"] == device_id:
                device_name = d["name"]
                break
    finally:
        reader.close()
        
    if not samples:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(None, fh)
        return
        
    base_profile_str = '{"meta":{"interval":1000,"startTime":0,"abi":"","misc":"","oscpu":"","platform":"","processType":0,"extensions":{"id":[],"name":[],"baseURL":[],"length":0},"categories":[{"name":"Other","color":"grey","subcategories":["Other"]}],"product":"Home power profiling","stackwalk":0,"toolkit":"","version":27,"preprocessedProfileVersion":48,"appBuildID":"","sourceURL":"","symbolicationNotSupported":true,"markerSchema":[]},"libs":[],"pages":[],"threads":[{"processType":"default","processStartupTime":0,"processShutdownTime":null,"registerTime":0,"unregisterTime":null,"pausedRanges":[],"name":"GeckoMain","isMainThread":true,"pid":"0","tid":0,"samples":{"weightType":"samples","weight":null,"eventDelay":[],"stack":[],"time":[],"length":0},"markers":{"data":[],"name":[],"startTime":[],"endTime":[],"phase":[],"category":[],"length":0},"stackTable":{"frame":[0],"prefix":[null],"category":[0],"subcategory":[0],"length":1},"frameTable":{"address":[-1],"inlineDepth":[0],"category":[null],"subcategory":[0],"func":[0],"nativeSymbol":[null],"innerWindowID":[0],"implementation":[null],"line":[null],"column":[null],"length":1},"stringTable":{"_array":["(root)"],"_stringToIndex":{}},"funcTable":{"isJS":[false],"relevantForJS":[false],"name":[0],"resource":[-1],"fileName":[null],"lineNumber":[null],"columnNumber":[null],"length":1},"resourceTable":{"lib":[],"name":[],"host":[],"type":[],"length":0},"nativeSymbols":{"libIndex":[],"address":[],"name":[],"functionSize":[],"length":0}}],"counters":[]}'
    profile = json.loads(base_profile_str)
    
    profile["meta"]["markerSchema"] = [
        {"name": "volt", "tooltipLabel": "{marker.data.v}", "display": [], "data": [{"key": "v", "label": "Voltage", "format": "string"}], "graphs": [{"key": "v", "color": "orange", "type": "line-filled"}]},
        {"name": "amp", "tooltipLabel": "{marker.data.a} A", "display": [], "data": [{"key": "a", "label": "Current (A)", "format": "string"}], "graphs": [{"key": "a", "color": "red", "type": "line-filled"}]},
        {"name": "pf", "tooltipLabel": "{marker.data.pf}", "display": [], "data": [{"key": "pf", "label": "Power factor", "format": "string"}], "graphs": [{"key": "pf", "color": "blue", "type": "line-filled"}]},
        {"name": "freq", "tooltipLabel": "{marker.data.f} Hz", "display": [], "data": [{"key": "f", "label": "Frequency (Hz)", "format": "string"}], "graphs": [{"key": "f", "color": "grey", "type": "line-filled"}]},
        {"name": "range", "tooltipLabel": "{marker.data.range}", "display": ["marker-chart", "marker-table"], "data": [{"key": "range", "label": "Range", "format": "string"}, {"key": "from", "label": "From", "format": "string"}]}
    ]
    
    # Times in ms
    times = [round(s["ts"] * 1000) for s in samples]
    
    # Calculate intervals and energy
    avg_interval_ms = 1000
    if len(times) > 1:
        avg_interval_ms = round((times[-1] - times[0]) / (len(times) - 1))
        
    profile["meta"]["interval"] = avg_interval_ms
    profile["meta"]["startTime"] = 0 
    profile["meta"]["profilingStartTime"] = 0
    profile["meta"]["profilingEndTime"] = times[-1] if times else 0
    profile["meta"]["product"] = device_name
    
    zeros = [0] * len(times)
    thread = profile["threads"][0]
    thread["samples"]["stack"] = zeros
    thread["samples"]["time"] = times
    thread["samples"]["length"] = len(times)
    
    energy_data = []
    for i in range(len(samples)):
        power = samples[i].get("power_w")
        if power is None or math.isnan(power):
            power = 0.0
            
        if i == 0:
            interval_s = avg_interval_ms / 1000.0
        else:
            interval_s = (times[i] - times[i-1]) / 1000.0
            
        energy_data.append(_watt_second_to_pico_watt_hour(power * interval_s))
        
    profile["counters"] = [
        _counter_object(device_name, f"Data recorded by a {device_name} power meter", times, energy_data)
    ]
    
    markers = thread["markers"]
    string_table = thread["stringTable"]["_array"]
    
    def add_instant_marker(start_time, name_index, data):
        markers["startTime"].append(start_time)
        markers["endTime"].append(None)
        markers["phase"].append(0)
        markers["category"].append(0)
        markers["name"].append(name_index)
        markers["data"].append(data)
        
    # Volt
    volt_idx = len(string_table)
    string_table.append("Voltage")
    for i, s in enumerate(samples):
        v = s.get("voltage_v")
        if v is not None and not math.isnan(v):
            add_instant_marker(times[i], volt_idx, {"type": "volt", "v": str(v)})
            
    # Amp
    amp_idx = len(string_table)
    string_table.append("Current")
    for i, s in enumerate(samples):
        a = s.get("current_a")
        if a is not None and not math.isnan(a):
            add_instant_marker(times[i], amp_idx, {"type": "amp", "a": str(a)})
            
    # PF
    pf_idx = len(string_table)
    string_table.append("Power Factor")
    for i, s in enumerate(samples):
        pf = s.get("pf")
        if pf is not None and not math.isnan(pf):
            add_instant_marker(times[i], pf_idx, {"type": "pf", "pf": str(pf)})
            
    # Voltage Range
    vrange_idx = len(string_table)
    string_table.append("Voltage Range")
    for i, s in enumerate(samples):
        vr = s.get("v_range")
        if not vr: continue
        prev_vr = samples[i-1].get("v_range") if i > 0 else None
        if i == 0 or i == len(samples) - 1 or vr != prev_vr:
            data = {"type": "range", "range": vr}
            if i > 0 and vr != prev_vr and prev_vr:
                data["from"] = prev_vr
            add_instant_marker(times[i], vrange_idx, data)
            
    # Current Range
    irange_idx = len(string_table)
    string_table.append("Current Range")
    for i, s in enumerate(samples):
        ir = s.get("i_range")
        if not ir: continue
        prev_ir = samples[i-1].get("i_range") if i > 0 else None
        if i == 0 or i == len(samples) - 1 or ir != prev_ir:
            data = {"type": "range", "range": ir}
            if i > 0 and ir != prev_ir and prev_ir:
                data["from"] = prev_ir
            add_instant_marker(times[i], irange_idx, data)
            
    markers["length"] = len(markers["name"])
    
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, separators=(',', ':'))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export DB to CSV or Firefox Profiler JSON")
    parser.add_argument("--db", required=True, help="Path to DB")
    parser.add_argument("--device-id", required=True, type=int, help="Device ID (or input device ID for efficiency-csv)")
    parser.add_argument("--pair-device-id", type=int, help="Output device ID (required for efficiency-csv)")
    parser.add_argument("--out", required=True, help="Output path")
    parser.add_argument("--format", required=True, choices=["csv", "profile", "efficiency-csv"], help="Export format")
    parser.add_argument("--start", type=float, default=0.0, help="Start timestamp")
    parser.add_argument("--end", type=float, default=2e9, help="End timestamp")
    args = parser.parse_args()
    
    if args.format == "csv":
        export_csv(args.db, args.device_id, args.start, args.end, args.out)
    elif args.format == "efficiency-csv":
        if not args.pair_device_id:
            print("Error: --pair-device-id is required when --format is efficiency-csv")
            exit(1)
        export_paired_efficiency_csv(args.db, args.device_id, args.pair_device_id, args.start, args.end, args.out)
    else:
        export_firefox_profile(args.db, args.device_id, args.start, args.end, args.out)
