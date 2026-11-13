#!/usr/bin/env python3
"""Platform-side latency from the OverheadLatency vended metric (V2 only).

AgentCore Runtime started emitting OverheadLatency for V2 runtimes in November
2026. It measures from when the service receives a request to when the agent
returns its first response byte, minus the agent's own processing. Comparing it
with the client-side latency recorded by bench.py splits each cold start into
"platform" and "everything else" (network path, SigV4, response transfer).

The metric's dimension set is not documented, so it is discovered with
ListMetrics and matched to each runtime by ARN, id or name.

Usage:
  python scripts/overhead.py            # after bench.py, wait ~5 min first
"""

import json
import math
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402

METRICS = ("OverheadLatency", "Latency")
STATS = ["p50", "p75", "p90", "p99"]


def discover(cw, metric: str) -> list[list[dict]]:
    dims = []
    for page in cw.get_paginator("list_metrics").paginate(
        Namespace="AWS/Bedrock-AgentCore", MetricName=metric
    ):
        for m in page["Metrics"]:
            dims.append(m["Dimensions"])
    return dims


def matches(dimset: list[dict], meta: dict, name: str) -> bool:
    vals = {d["Value"] for d in dimset}
    keys = {meta.get("arn"), meta.get("runtime_id"), name}
    return bool(vals & keys) or any(meta.get("arn", "") and meta["arn"] in v for v in vals)


PREFERRED_DIMS = {"Name", "Operation", "Resource"}


def pick_dimset(sets: list[list[dict]]):
    """Same dimension set for both metrics when possible, else the narrowest."""
    exact = [ds for ds in sets if {d["Name"] for d in ds} == PREFERRED_DIMS]
    if exact:
        return exact[0]
    return sorted(sets, key=len)[0] if sets else None


def window_stats(cw, metric: str, dimset: list[dict], start, end) -> dict:
    """One datapoint covering the whole window, so percentiles are not merged."""
    start = start.replace(second=0, microsecond=0)
    period = max(60, math.ceil((end - start).total_seconds() / 60) * 60)
    r = cw.get_metric_statistics(
        Namespace="AWS/Bedrock-AgentCore",
        MetricName=metric,
        Dimensions=dimset,
        StartTime=start,
        EndTime=start + timedelta(seconds=period),
        Period=period,
        Statistics=["SampleCount", "Average", "Minimum", "Maximum"],
        ExtendedStatistics=STATS,
    )
    dps = r.get("Datapoints", [])
    if not dps:
        return {}
    dp = max(dps, key=lambda d: d.get("SampleCount", 0))
    out = {
        "unit": dp.get("Unit"),
        "samples": dp.get("SampleCount"),
        "avg": round(dp["Average"], 1),
        "min": round(dp["Minimum"], 1),
        "max": round(dp["Maximum"], 1),
    }
    out.update({k: round(v, 1) for k, v in dp.get("ExtendedStatistics", {}).items()})
    return out


def main() -> int:
    state = json.loads(C.STATE_FILE.read_text())
    cw = boto3.client("cloudwatch", region_name=C.REGION)
    found = {m: discover(cw, m) for m in METRICS}
    doc = {
        "region": C.REGION,
        "dimension_sets_seen": {
            m: sorted({tuple(sorted(d["Name"] for d in ds)) for ds in v}) for m, v in found.items()
        },
        "rows": [],
    }

    for scen in ("cold", "burst", "warm"):
        p = C.RESULTS_DIR / f"bench-{scen}.json"
        if not p.exists():
            continue
        bench = json.loads(p.read_text())
        scen_start = datetime.fromisoformat(bench["started_utc"])
        scen_end = datetime.fromisoformat(bench["finished_utc"])
        for name, meta in state.items():
            res = bench["results"].get(name)
            if not res:
                continue
            # Per-leg windows (bench.py records them since 2026-11-13) keep the
            # minute buckets of one leg apart from the next scenario's leg on
            # the same runtime, provided the run used --gap > 60. Older runs
            # only have the scenario window, which can overlap neighbours.
            if res.get("leg_start_utc"):
                start = datetime.fromisoformat(res["leg_start_utc"])
                end = datetime.fromisoformat(res["leg_end_utc"]) + timedelta(seconds=59)
                window = "leg"
            else:
                start, end = scen_start - timedelta(minutes=1), scen_end + timedelta(minutes=2)
                window = "scenario (may overlap other scenarios)"
            client = res["summary"]
            row = {
                "scenario": scen,
                "runtime": name,
                "version": meta["platform_version"],
                "client_p50_ms": client["p50_ms"],
                "client_p75_ms": client["p75_ms"],
                "client_samples": client["ok"],
                "window": window,
                "window_start_utc": start.isoformat(),
                "window_end_utc": end.isoformat(),
            }
            for metric in METRICS:
                ds = pick_dimset([ds for ds in found[metric] if matches(ds, meta, name)])
                row[metric] = window_stats(cw, metric, ds, start, end) if ds else {}
                row[f"{metric}_dims"] = [d["Name"] for d in ds] if ds else None
            doc["rows"].append(row)
            o, lat = row["OverheadLatency"], row["Latency"]
            print(
                f"[overhead] {scen:<5} {name:<20} client p50={row['client_p50_ms']} "
                f"| Latency p50={lat.get('p50')} | OverheadLatency p50={o.get('p50')} "
                f"n={o.get('samples')} {o.get('unit')}"
            )

    out = C.RESULTS_DIR / "overhead.json"
    out.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[overhead] dimension sets: {doc['dimension_sets_seen']}")
    print(f"[overhead] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
