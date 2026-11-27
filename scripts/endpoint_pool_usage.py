#!/usr/bin/env python3
"""Billed usage of the endpoint_pool_probe.py runtimes, per runtime and endpoint.

Run about 60 minutes after the probe finished. Usage metrics are published
with Resource = runtime ARN and Service = AgentCore.Runtime, and also with an
extra Name = "<runtime name>::<endpoint>" dimension, so the creation-time
metering can be attributed to each endpoint.

Two windows are reported per series:
  creation  one minute before the first create call -> burst start
  burst     burst start -> five minutes after deletion (burst + refill)

Usage:
  python scripts/endpoint_pool_usage.py results-seoul/endpoint_pool-0410.json
"""

import json
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402
import boto3  # noqa: E402

METRICS = ("MemoryUsed-GBHours", "CPUUsed-vCPUHours")


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def series(cw, metric, dims, start, end):
    resp = cw.get_metric_statistics(
        Namespace="AWS/Bedrock-AgentCore", MetricName=metric, Dimensions=dims,
        StartTime=start, EndTime=end, Period=60, Statistics=["Sum"],
    )
    return sorted((dp["Timestamp"], dp["Sum"]) for dp in resp.get("Datapoints", []))


def main() -> int:
    path = pathlib.Path(sys.argv[1])
    d = json.loads(path.read_text())
    cw = boto3.client("cloudwatch", region_name=d["region"])
    first = min(ts(r["created_utc"]) for r in d["runtimes"].values())
    burst = ts(d["burst_start_utc"])
    last = max(ts(r.get("deleted_utc", d["burst_end_utc"])) for r in d["runtimes"].values())
    # CloudWatch stamps each 60 s bucket with its start, so the bucket that holds
    # the burst starts before burst_start_utc. Split on the burst's minute.
    burst_min = burst.replace(second=0, microsecond=0)
    w_create = (first - timedelta(minutes=1), burst_min)
    w_burst = (burst_min, last + timedelta(minutes=5))
    out = {"source": path.name, "windows": {"creation": [str(x) for x in w_create],
                                            "burst": [str(x) for x in w_burst]}, "series": {}}

    for kind, rt in d["runtimes"].items():
        base = [{"Name": "Resource", "Value": rt["arn"]}, {"Name": "Service", "Value": "AgentCore.Runtime"}]
        targets = {"(runtime)": base}
        for ep in rt["endpoints"]:
            targets[ep] = base + [{"Name": "Name", "Value": f"{rt['name']}::{ep}"}]
        for label, dims in targets.items():
            key = f"{kind}::{label}"
            row = {}
            for m in METRICS:
                pts = series(cw, m, dims, w_create[0], w_burst[1])
                row[m] = {
                    "creation": round(sum(v for t, v in pts if t < w_create[1]), 6),
                    "burst": round(sum(v for t, v in pts if t >= w_burst[0]), 6),
                    "points": [[t.isoformat(), round(v, 6)] for t, v in pts],
                }
            out["series"][key] = row
            print(f"{key:28s} GB-h creation {row['MemoryUsed-GBHours']['creation']:.4f} "
                  f"burst {row['MemoryUsed-GBHours']['burst']:.4f} | vCPU-h creation "
                  f"{row['CPUUsed-vCPUHours']['creation']:.4f} burst {row['CPUUsed-vCPUHours']['burst']:.4f}")

    dst = path.with_name(path.stem + "-usage.json")
    dst.write_text(json.dumps(out, indent=2))
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
