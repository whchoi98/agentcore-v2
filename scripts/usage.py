#!/usr/bin/env python3
"""Collect billed usage per runtime from CloudWatch and price it.

Metrics live in namespace AWS/Bedrock-AgentCore with dimensions
Resource = the runtime ARN and Service = AgentCore.Runtime:

  MemoryUsed-GBHours   memory actually billed
  CPUUsed-vCPUHours    CPU actually billed
  Sessions             session count (dimensioned by Operation, not Service)

Two cautions carried over from the AWS sample, because they change how the
numbers should be read:

  * A daily total lumps every run against a runtime together. This script
    windows on the benchmark's own start/finish timestamps instead.
  * GB-hours per session mixes footprint with how long sessions lived. The V1
    2 GB leg's sessions lived ~30 s because the cold start itself took that
    long, while V2 sessions lived ~2 s. Dividing by session-hours isolates the
    footprint; session duration here is approximated from client-observed
    latency, so treat the footprint column as indicative, not exact.
"""

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402

USAGE_METRICS = ("MemoryUsed-GBHours", "CPUUsed-vCPUHours")


def sum_metric(cw, metric: str, arn: str, start, end, dims) -> float:
    total = 0.0
    resp = cw.get_metric_statistics(
        Namespace="AWS/Bedrock-AgentCore",
        MetricName=metric,
        Dimensions=dims,
        StartTime=start,
        EndTime=end,
        Period=300,
        Statistics=["Sum"],
    )
    for dp in resp.get("Datapoints", []):
        total += dp["Sum"]
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    # The first (Tokyo) round opened the window 10 minutes before the first
    # scenario. In the Seoul round that swept in usage that a V1 runtime meters
    # in the minute it is created, with no invocation at all (pre-initialized
    # environments, it appears). 1 minute excludes it when the bench starts
    # more than a minute after the last deploy.
    ap.add_argument("--pre-pad-min", type=float, default=10.0)
    ap.add_argument("--out", default="usage.json")
    args = ap.parse_args()
    state = json.loads(C.STATE_FILE.read_text())
    cw = boto3.client("cloudwatch", region_name=C.REGION)

    # Window the query on the benchmark runs themselves.
    starts, ends = [], []
    bench_docs = {}
    for scen in ("cold", "burst", "warm"):
        p = C.RESULTS_DIR / f"bench-{scen}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        bench_docs[scen] = d
        starts.append(datetime.fromisoformat(d["started_utc"]))
        ends.append(datetime.fromisoformat(d["finished_utc"]))
    if not starts:
        sys.exit("no bench-*.json found; run scripts/bench.py first")

    # Pad: usage lands in a burst at session teardown, after the run finishes.
    start = min(starts) - timedelta(minutes=args.pre_pad_min)
    end = max(ends) + timedelta(minutes=25)
    print(f"[usage] window {start.isoformat()} .. {end.isoformat()}")

    # Sessions and observed session-seconds attributable to this experiment,
    # summed across the three scenarios from the client's own records.
    per_runtime_client = {}
    for scen, d in bench_docs.items():
        for name, res in d["results"].items():
            acc = per_runtime_client.setdefault(name, {"sessions": 0, "session_s": 0.0})
            recs = res["records"]
            if scen == "warm":
                # One session for the whole leg, held for cold + all warm calls.
                acc["sessions"] += 1
                acc["session_s"] += (
                    (res["first"].get("latency_ms") or 0)
                    + sum(r.get("latency_ms") or 0 for r in recs)
                ) / 1000.0
            else:
                acc["sessions"] += len(recs)
                acc["session_s"] += sum(r.get("latency_ms") or 0 for r in recs) / 1000.0

    rows = []
    for name, meta in state.items():
        arn = meta["arn"]
        dims = [
            {"Name": "Resource", "Value": arn},
            {"Name": "Service", "Value": "AgentCore.Runtime"},
        ]
        gbh = sum_metric(cw, "MemoryUsed-GBHours", arn, start, end, dims)
        cpuh = sum_metric(cw, "CPUUsed-vCPUHours", arn, start, end, dims)
        version = meta["platform_version"]
        rate = C.RATES[version]
        cost_mem = gbh * rate["gb_hour"]
        cost_cpu = cpuh * rate["vcpu_hour"]
        cli = per_runtime_client.get(name, {"sessions": 0, "session_s": 0.0})
        session_h = cli["session_s"] / 3600.0
        rows.append(
            {
                "runtime": name,
                "size": meta["size"],
                "version": version,
                "sessions": cli["sessions"],
                "observed_session_hours": round(session_h, 5),
                "gb_hours": round(gbh, 4),
                "vcpu_hours": round(cpuh, 4),
                "gb_hours_per_session": round(gbh / cli["sessions"], 5)
                if cli["sessions"]
                else None,
                # GB-hours / session-hours = average billed memory footprint.
                "implied_footprint_gb": round(gbh / session_h, 2) if session_h else None,
                "cost_memory_usd": round(cost_mem, 4),
                "cost_cpu_usd": round(cost_cpu, 4),
                "cost_total_usd": round(cost_mem + cost_cpu, 4),
            }
        )

    doc = {
        "region": C.REGION,
        "window_start_utc": start.isoformat(),
        "pre_pad_min": args.pre_pad_min,
        "window_end_utc": end.isoformat(),
        "rates_usd": C.RATES,
        "rows": rows,
        "experiment_total_usd": round(sum(r["cost_total_usd"] for r in rows), 4),
    }
    out = C.RESULTS_DIR / args.out
    out.write_text(json.dumps(doc, indent=2))

    hdr = f"{'runtime':<20}{'sess':>6}{'GB-h':>9}{'vCPU-h':>9}{'footprint':>11}{'cost$':>9}"
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(rows, key=lambda x: (x["size"], x["version"])):
        print(
            f"{r['runtime']:<20}{r['sessions']:>6}{r['gb_hours']:>9.3f}"
            f"{r['vcpu_hours']:>9.3f}{str(r['implied_footprint_gb'])+' GB':>11}"
            f"{r['cost_total_usd']:>9.3f}"
        )
    print(f"\n[usage] experiment total: ${doc['experiment_total_usd']:.2f}")
    print(f"[usage] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
