#!/usr/bin/env python3
"""Elastic-memory scenario: does V2 reclaim memory a session has released?

The cold-start scenarios say nothing about this, because the echo agent never
allocates. Here each session does one invoke that allocates N MB, writes every
page so it is genuinely resident, frees it, and returns. The client then holds
the session idle for a fixed period and stops it.

  V1 bills the session's peak memory for the rest of its life.
  V2 is supposed to reclaim memory that has gone cold, so the same session
  should meter fewer GB-hours.

A control condition runs the identical session shape with no allocation, which
isolates how much of the bill the spike itself is responsible for rather than
attributing baseline session cost to it.

Usage:
  python scripts/mem_bench.py deploy          # create the two runtimes
  python scripts/mem_bench.py run [--mb 1536] [--idle 90] [--reps 3]
  python scripts/mem_bench.py collect         # pull GB-hours and compare
"""

import argparse
import concurrent.futures as cf
import json
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402
import bench as B  # noqa: E402
import deploy as D  # noqa: E402

MEM_TAG = "mem"
MEM_STATE = C.RESULTS_DIR / "mem_runtimes.json"
RUN_FILE = C.RESULTS_DIR / "mem_runs.json"

# Longer than the client's idle period so the client, not the service, decides
# when the session ends; otherwise AgentCore reaps it mid-measurement.
MEM_IDLE_TIMEOUT_S = 180
MEM_MAX_LIFETIME_S = 300


def do_deploy() -> int:
    acct = C.account_id()
    role_arn = D.ensure_role(acct)
    ctl = C.control_client()
    uri = C.image_uri(MEM_TAG, acct)
    state = json.loads(MEM_STATE.read_text()) if MEM_STATE.exists() else {}

    for version in C.PLATFORM_VERSIONS:
        name = f"{C.RUNTIME_PREFIX}_mem_{version}"
        common = dict(
            roleArn=role_arn,
            agentRuntimeArtifact={"containerConfiguration": {"containerUri": uri}},
            networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration={"serverProtocol": "HTTP"},
            lifecycleConfiguration={
                "idleRuntimeSessionTimeout": MEM_IDLE_TIMEOUT_S,
                "maxLifetime": MEM_MAX_LIFETIME_S,
            },
            environmentVariables={
                "IMAGE_SIZE_LABEL": MEM_TAG,
                "PLATFORM_VERSION_LABEL": version,
            },
            **C.platform_kwargs(version),
        )
        existing = D.find_runtime(ctl, name)
        if existing:
            rid = existing["agentRuntimeId"]
            print(f"[mem] updating {name}")
            ctl.update_agent_runtime(agentRuntimeId=rid, **common)
        else:
            print(f"[mem] creating {name}")
            rid = ctl.create_agent_runtime(agentRuntimeName=name, **common)["agentRuntimeId"]
        status, ready_s = D.wait_ready(ctl, rid)
        got = ctl.get_agent_runtime(agentRuntimeId=rid)
        print(f"[mem]   {name}: {status} in {ready_s:.1f}s (pv={got.get('platformVersion')})")
        state[name] = {
            "version": got.get("platformVersion", version),
            "platform_version_field_sent": common.get(
                "platformVersion", "(omitted: service default)"
            ),
            "runtime_id": rid,
            "arn": got["agentRuntimeArn"],
            "status": status,
            "ready_s": round(ready_s, 2),
            "idle_timeout_s": MEM_IDLE_TIMEOUT_S,
            "max_lifetime_s": MEM_MAX_LIFETIME_S,
        }
        MEM_STATE.write_text(json.dumps(state, indent=2))
    return 0


def one_session(client, arn: str, mb: int, idle_s: float, alloc: bool, seq: int) -> dict:
    """One session: one invoke (optionally allocating), then a fixed idle, then stop."""
    sid = B.new_session_id()
    payload = (
        {"mode": "alloc", "mb": mb, "hold_s": 2.0}
        if alloc
        else {"mode": "echo", "seq": seq}
    )
    t0 = time.perf_counter()
    rec = {"seq": seq, "alloc": alloc, "session_id": sid}
    try:
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=sid,
            qualifier="DEFAULT",
            contentType="application/json",
            accept="application/json",
            payload=json.dumps(payload).encode(),
        )
        out = json.loads(resp["response"].read()).get("output", {})
        rec["invoke_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        rec["ok"] = True
        rec["memory_profile"] = out.get("memory_profile")
        rec["rss_mb"] = out.get("rss_mb")
        rec["boot_id"] = out.get("boot_id")
    except Exception as e:  # noqa: BLE001 - record and continue
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        rec["invoke_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    time.sleep(idle_s)  # session sits idle, holding whatever the platform holds
    B.stop_session(client, arn, sid)
    rec["session_wall_s"] = round(time.perf_counter() - t0, 1)
    return rec


def do_run(mb: int, idle_s: float, reps: int) -> int:
    if not MEM_STATE.exists():
        sys.exit("run `mem_bench.py deploy` first")
    state = json.loads(MEM_STATE.read_text())
    client = C.data_client(max_pool=40, read_timeout=180)
    doc = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "alloc_mb": mb,
        "idle_s": idle_s,
        "reps": reps,
        "legs": {},
        "leg_windows": {},
    }
    first = True
    for name, meta in state.items():
        arn = meta["arn"]
        for alloc in (True, False):
            # Quiet gap so each leg's usage falls in its own minute buckets and
            # can be attributed to that leg rather than smeared across two.
            if not first:
                print("[mem] quiet gap 150s")
                time.sleep(150)
            first = False
            label = f"{name}:{'alloc' if alloc else 'control'}"
            print(f"[mem] {label}: {reps} sessions, {mb if alloc else 0} MB spike, idle {idle_s}s")
            t_start = datetime.now(timezone.utc)
            with cf.ThreadPoolExecutor(max_workers=reps) as ex:
                recs = list(
                    ex.map(
                        lambda i: one_session(client, arn, mb, idle_s, alloc, i),
                        range(reps),
                    )
                )
            t_end = datetime.now(timezone.utc)
            doc["legs"][label] = recs
            doc["leg_windows"][label] = {
                "runtime": name,
                "alloc": alloc,
                "start_utc": t_start.isoformat(),
                "end_utc": t_end.isoformat(),
                "session_hours": round(sum(r["session_wall_s"] for r in recs) / 3600.0, 5),
            }
            prof = next((r["memory_profile"] for r in recs if r.get("memory_profile")), None)
            print(f"[mem]   invoke_ms={[r['invoke_ms'] for r in recs]} rss_profile={prof}")
            C.RESULTS_DIR.joinpath("mem_runs.json").write_text(json.dumps(doc, indent=2))
    doc["finished_utc"] = datetime.now(timezone.utc).isoformat()
    RUN_FILE.write_text(json.dumps(doc, indent=2))
    print(f"[mem] wrote {RUN_FILE}")
    return 0


def do_collect() -> int:
    doc = json.loads(RUN_FILE.read_text())
    state = json.loads(MEM_STATE.read_text())
    cw = boto3.client("cloudwatch", region_name=C.REGION)

    def gb_hours(arn, start, end):
        r = cw.get_metric_statistics(
            Namespace="AWS/Bedrock-AgentCore",
            MetricName="MemoryUsed-GBHours",
            Dimensions=[
                {"Name": "Resource", "Value": arn},
                {"Name": "Service", "Value": "AgentCore.Runtime"},
            ],
            StartTime=start,
            EndTime=end,
            Period=60,
            Statistics=["Sum"],
        )
        return sum(dp["Sum"] for dp in r.get("Datapoints", []))

    windows = doc.get("leg_windows", {})
    if not windows:
        sys.exit("mem_runs.json has no leg_windows; re-run `mem_bench.py run`")

    rows = []
    for label, w in windows.items():
        arn = state[w["runtime"]]["arn"]
        version = state[w["runtime"]]["version"]
        # A leg's usage is emitted while its sessions run and at their teardown;
        # the quiet gap between legs keeps the tail inside this window.
        start = datetime.fromisoformat(w["start_utc"]) - timedelta(seconds=30)
        end = datetime.fromisoformat(w["end_utc"]) + timedelta(seconds=120)
        gbh = gb_hours(arn, start, end)
        sh = w["session_hours"]
        rows.append(
            {
                "leg": label,
                "runtime": w["runtime"],
                "version": version,
                "condition": "alloc" if w["alloc"] else "control",
                "sessions": len(doc["legs"][label]),
                "session_hours": sh,
                "gb_hours": round(gbh, 4),
                "implied_footprint_gb": round(gbh / sh, 2) if sh else None,
                "median_invoke_ms": sorted(r["invoke_ms"] for r in doc["legs"][label])[
                    len(doc["legs"][label]) // 2
                ],
                "cost_memory_usd": round(gbh * C.RATES[version]["gb_hour"], 5),
            }
        )

    # The spike's own contribution: alloc footprint minus control footprint.
    deltas = {}
    for ver in C.PLATFORM_VERSIONS:
        a = next((r for r in rows if r["version"] == ver and r["condition"] == "alloc"), None)
        c = next((r for r in rows if r["version"] == ver and r["condition"] == "control"), None)
        if a and c and a["implied_footprint_gb"] and c["implied_footprint_gb"]:
            deltas[ver] = {
                "alloc_footprint_gb": a["implied_footprint_gb"],
                "control_footprint_gb": c["implied_footprint_gb"],
                "spike_attributable_gb": round(
                    a["implied_footprint_gb"] - c["implied_footprint_gb"], 2
                ),
                "alloc_vs_control_gbh_ratio": round(
                    a["gb_hours"] / c["gb_hours"], 2
                )
                if c["gb_hours"]
                else None,
            }

    out = {"alloc_mb": doc["alloc_mb"], "idle_s": doc["idle_s"], "rows": rows, "deltas": deltas}
    (C.RESULTS_DIR / "mem_usage.json").write_text(json.dumps(out, indent=2))

    hdr = f"{'leg':<28}{'sess':>5}{'sess-h':>9}{'GB-h':>9}{'footprint':>12}{'invoke ms':>11}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['leg']:<28}{r['sessions']:>5}{r['session_hours']:>9.4f}{r['gb_hours']:>9.4f}"
            f"{str(r['implied_footprint_gb'])+' GB':>12}{r['median_invoke_ms']:>11.0f}"
        )
    print()
    for ver, d in deltas.items():
        print(
            f"{ver}: spike adds {d['spike_attributable_gb']} GB to the billed footprint "
            f"({d['control_footprint_gb']} -> {d['alloc_footprint_gb']} GB, "
            f"GB-h ratio {d['alloc_vs_control_gbh_ratio']}x)"
        )
    print(f"[mem] wrote {C.RESULTS_DIR / 'mem_usage.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["deploy", "run", "collect"])
    ap.add_argument("--mb", type=int, default=1536)
    ap.add_argument("--idle", type=float, default=90.0)
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    if a.command == "deploy":
        return do_deploy()
    if a.command == "run":
        return do_run(a.mb, a.idle, a.reps)
    return do_collect()


if __name__ == "__main__":
    raise SystemExit(main())
