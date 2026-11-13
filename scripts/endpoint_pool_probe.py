#!/usr/bin/env python3
"""Does each V1 endpoint keep its own pool of pre-initialized environments?

A co-author's Seoul measurements (2026-11-09, V1, 1 GB image) found about ten
pre-warmed microVMs per endpoint right after creation and suggested spreading
requests round-robin over several endpoints of one runtime so that more
sessions land on a pre-warmed environment. That note shows the single-endpoint
pool, not a multi-endpoint result, so this script measures it directly.

Two fresh V1 runtimes are created from the same 1gb image:

  single  DEFAULT endpoint only
  rr3     DEFAULT + rr1 + rr2, all pointing at version 1

After a settle period both runtimes receive N new sessions at the same moment
(rr3 spreads them round-robin over its three endpoints). A session counts as
fast when it answers under FAST_MS; slow ones paid a full V1 cold start.

V1 also meters usage for the environments it prepares at creation, with no
invocation. Billed usage is dimensioned per endpoint (Name = runtime::endpoint),
so endpoint_pool_usage.py can later show whether every extra endpoint adds
that creation-time cost. CloudWatch needs about 60 minutes before those
numbers settle; the timestamps recorded here are the windows it uses.

Usage:
  python scripts/endpoint_pool_probe.py [--sessions 30] [--settle 300]
                                        [--post 180] [--keep] --suffix=-0410
"""

import argparse
import json
import pathlib
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench as B  # noqa: E402
import config as C  # noqa: E402
import deploy as D  # noqa: E402

PREFIX = "acpool"
SIZE = "1gb"
EXTRA_ENDPOINTS = ("rr1", "rr2")
# Pre-warmed sessions answered in 0.3-1.3 s and full V1 cold starts of the 1gb
# image took 13-16 s in both the co-author's and this lab's runs, so 3 s
# separates the two clusters with a wide margin.
FAST_MS = 3000


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def runtime_config(role_arn: str, uri: str) -> dict:
    return dict(
        roleArn=role_arn,
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": uri}},
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
        lifecycleConfiguration={
            "idleRuntimeSessionTimeout": C.IDLE_TIMEOUT_S,
            "maxLifetime": C.MAX_LIFETIME_S,
        },
        environmentVariables={"IMAGE_SIZE_LABEL": SIZE, "PLATFORM_VERSION_LABEL": "V1"},
        platformVersion="V1",
    )


def wait_endpoint(ctl, rid: str, name: str, timeout_s: int = 600) -> tuple[str, float]:
    t0 = time.perf_counter()
    while True:
        st = ctl.get_agent_runtime_endpoint(agentRuntimeId=rid, endpointName=name)["status"]
        if st == "READY" or st.endswith("FAILED"):
            return st, time.perf_counter() - t0
        if time.perf_counter() - t0 > timeout_s:
            return f"TIMEOUT({st})", time.perf_counter() - t0
        time.sleep(3)


def summarize(recs: list[dict]) -> dict:
    ok = [r for r in recs if r.get("ok")]
    fast = [r for r in ok if r["latency_ms"] < FAST_MS]
    slow = [r for r in ok if r["latency_ms"] >= FAST_MS]

    def med(rs, key="latency_ms"):
        vals = [r[key] for r in rs if r.get(key) is not None]
        return round(statistics.median(vals), 2) if vals else None

    return {
        "sessions": len(recs),
        "ok": len(ok),
        "errors": sorted({r.get("error") for r in recs if not r.get("ok")} - {None}),
        "fast": len(fast),
        "slow": len(slow),
        "fast_median_ms": med(fast),
        "slow_median_ms": med(slow),
        "fast_median_uptime_mono_s": med(fast, "uptime_mono_s"),
        "slow_median_uptime_mono_s": med(slow, "uptime_mono_s"),
        "distinct_boot_ids": len({r.get("boot_id") for r in ok}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=30, help="new sessions per runtime")
    ap.add_argument("--settle", type=int, default=300, help="seconds between READY and the burst")
    ap.add_argument("--post", type=int, default=180, help="seconds to keep runtimes after the burst")
    ap.add_argument("--keep", action="store_true", help="do not delete the runtimes")
    ap.add_argument("--suffix", required=True, help="result file suffix, e.g. -0410")
    args = ap.parse_args()

    acct = C.account_id()
    role_arn = D.ensure_role(acct)
    uri = C.image_uri(SIZE, acct)
    ctl = C.control_client()
    tag = args.suffix.lstrip("-").replace("-", "_")
    out = {"started_utc": utcnow(), "region": C.REGION, "image": SIZE, "fast_ms": FAST_MS,
           "sessions_per_runtime": args.sessions, "settle_s": args.settle, "runtimes": {}}

    # 1. Create both runtimes back to back so they share the same conditions.
    for kind in ("single", "rr3"):
        name = f"{PREFIX}_{kind}_{tag}"
        t_create = utcnow()
        rid = ctl.create_agent_runtime(agentRuntimeName=name, **runtime_config(role_arn, uri))["agentRuntimeId"]
        status, ready_s = D.wait_ready(ctl, rid)
        got = ctl.get_agent_runtime(agentRuntimeId=rid)
        out["runtimes"][kind] = {
            "name": name, "id": rid, "arn": got["agentRuntimeArn"],
            "platformVersion": got.get("platformVersion"), "status": status,
            "created_utc": t_create, "ready_s": round(ready_s, 1), "endpoints": {"DEFAULT": {}},
        }
        print(f"[pool] {name}: {status} in {ready_s:.1f}s platformVersion={got.get('platformVersion')}")

    rr = out["runtimes"]["rr3"]
    for ep in EXTRA_ENDPOINTS:
        t_ep = utcnow()
        ctl.create_agent_runtime_endpoint(agentRuntimeId=rr["id"], name=ep, agentRuntimeVersion="1")
        st, ep_s = wait_endpoint(ctl, rr["id"], ep)
        rr["endpoints"][ep] = {"created_utc": t_ep, "status": st, "ready_s": round(ep_s, 1)}
        print(f"[pool] {rr['name']}::{ep}: {st} in {ep_s:.1f}s")
    out["all_ready_utc"] = utcnow()

    # 2. Let every endpoint finish preparing its environments.
    print(f"[pool] settling {args.settle}s")
    time.sleep(args.settle)

    # 3. Same burst size on both runtimes, fired together.
    jobs = []
    quals = ["DEFAULT", *EXTRA_ENDPOINTS]
    for i in range(args.sessions):
        jobs.append(("single", out["runtimes"]["single"]["arn"], "DEFAULT", i))
        jobs.append(("rr3", rr["arn"], quals[i % len(quals)], i))
    client = C.data_client(max_pool=len(jobs) + 10)
    out["burst_start_utc"] = utcnow()
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = [(kind, q, ex.submit(B.cold_one, client, arn, i, q)) for kind, arn, q, i in jobs]
        recs = []
        for kind, q, f in futs:
            r = f.result()
            r.update(runtime=kind, qualifier=q)
            recs.append(r)
    out["burst_end_utc"] = utcnow()
    out["records"] = recs

    for kind in ("single", "rr3"):
        mine = [r for r in recs if r["runtime"] == kind]
        out["runtimes"][kind]["summary"] = summarize(mine)
        print(f"[pool] {kind}: {out['runtimes'][kind]['summary']}")
        for q in sorted({r["qualifier"] for r in mine}):
            s = summarize([r for r in mine if r["qualifier"] == q])
            out["runtimes"][kind]["endpoints"].setdefault(q, {})["summary"] = s
            print(f"[pool]   {kind}::{q}: fast {s['fast']} slow {s['slow']}")

    # 4. Save the burst before any cleanup call can fail.
    path = C.RESULTS_DIR / f"endpoint_pool{args.suffix}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[pool] wrote {path}", flush=True)

    # 5. Keep the runtimes a little so refill after the burst is metered in a
    #    separate window, then clean up. Endpoint deletion can take minutes and
    #    a runtime cannot be deleted while its endpoints are DELETING.
    if not args.keep:
        print(f"[pool] keeping {args.post}s for the refill window, then deleting", flush=True)
        time.sleep(args.post)
        for ep in EXTRA_ENDPOINTS:
            ctl.delete_agent_runtime_endpoint(agentRuntimeId=rr["id"], endpointName=ep)
        out["endpoint_delete_requested_utc"] = utcnow()
        for kind in ("single", "rr3"):
            rid = out["runtimes"][kind]["id"]
            for _ in range(200):
                try:
                    ctl.delete_agent_runtime(agentRuntimeId=rid)
                    out["runtimes"][kind]["deleted_utc"] = utcnow()
                    print(f"[pool] deleted {out['runtimes'][kind]['name']}", flush=True)
                    break
                except ctl.exceptions.ConflictException:
                    time.sleep(6)
            else:
                print(f"[pool] could not delete {out['runtimes'][kind]['name']}; delete it later", flush=True)
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(f"[pool] updated {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
