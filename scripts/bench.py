#!/usr/bin/env python3
"""Benchmark AgentCore Runtime V1 vs V2.

Three scenarios:

  cold   Each invoke uses a brand-new runtimeSessionId, so every measurement is
         a cold start. Run at low concurrency so the numbers isolate image size
         rather than mixing in queueing.
  burst  N cold sessions fired simultaneously, to test the claim that V2 start
         time is independent of concurrency.
  warm   One session reused for many sequential invokes, to establish the floor
         that cold start is measured against.

Sessions are stopped as soon as they are measured. AgentCore bills the whole
session lifecycle, and a benchmark session is idle for all of it, so leaving
them to age out is the single largest avoidable cost here.

Usage:
  python scripts/bench.py cold  [--n 30] [--concurrency 5]
  python scripts/bench.py burst [--n 50]
  python scripts/bench.py warm  [--n 30]
"""

import argparse
import concurrent.futures as cf
import json
import pathlib
import socket
import ssl
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402

THROTTLE = ("Throttl", "TooManyRequests", "ServiceQuotaExceeded", "LimitExceeded")


def new_session_id() -> str:
    """runtimeSessionId must be at least 33 characters."""
    return uuid.uuid4().hex + uuid.uuid4().hex


def measure_baseline_rtt(host: str, n: int = 10) -> dict:
    """TCP+TLS handshake RTT to the regional endpoint.

    The client runs in ap-northeast-2 and the runtimes in ap-northeast-1, so
    every latency figure below carries this round trip. Reporting it keeps the
    absolute numbers interpretable.
    """
    tcp, tls = [], []
    ctx = ssl.create_default_context()
    for _ in range(n):
        t0 = time.perf_counter()
        sock = socket.create_connection((host, 443), timeout=10)
        t1 = time.perf_counter()
        with ctx.wrap_socket(sock, server_hostname=host):
            t2 = time.perf_counter()
        tcp.append((t1 - t0) * 1000)
        tls.append((t2 - t0) * 1000)
    return {
        "host": host,
        "samples": n,
        "tcp_connect_ms_median": round(statistics.median(tcp), 2),
        "tcp_tls_ms_median": round(statistics.median(tls), 2),
    }


def invoke_once(client, arn: str, session_id: str, seq: int) -> dict:
    payload = json.dumps({"prompt": "ping", "seq": seq}).encode()
    t0 = time.perf_counter()
    rec = {"session_id": session_id, "seq": seq}
    try:
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=session_id,
            qualifier="DEFAULT",
            contentType="application/json",
            accept="application/json",
            payload=payload,
        )
        raw = resp["response"].read()
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        rec["ok"] = True
        try:
            out = json.loads(raw).get("output", {})
            for k in (
                "cold_start",
                "boot_id",
                "boot_pid",
                "uptime_wall_s",
                "uptime_mono_s",
                "req_id",
                "hostname",
                "handler_ms",
            ):
                rec[k] = out.get(k)
        except (ValueError, AttributeError):
            rec["parse_error"] = raw[:200].decode("utf-8", "replace")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "ClientError")
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        rec["ok"] = False
        rec["error"] = code
        rec["error_message"] = str(e)[:300]
        rec["throttled"] = any(m in code for m in THROTTLE)
    except Exception as e:  # noqa: BLE001 - record and continue the run
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        rec["ok"] = False
        rec["error"] = type(e).__name__
    return rec


def stop_session(client, arn: str, session_id: str) -> None:
    try:
        client.stop_runtime_session(
            agentRuntimeArn=arn, runtimeSessionId=session_id, qualifier="DEFAULT"
        )
    except Exception:  # noqa: BLE001 - teardown is best-effort
        pass


def cold_one(client, arn: str, seq: int) -> dict:
    sid = new_session_id()
    rec = invoke_once(client, arn, sid, seq)
    stop_session(client, arn, sid)
    return rec


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return round(s[k], 1)


def summarize(recs: list[dict]) -> dict:
    ok = [r for r in recs if r.get("ok")]
    lat = [r["latency_ms"] for r in ok]
    boots = {r.get("boot_id") for r in ok if r.get("boot_id")}
    reqs = [r.get("req_id") for r in ok if r.get("req_id")]
    wall = [r["uptime_wall_s"] for r in ok if r.get("uptime_wall_s") is not None]
    mono = [r["uptime_mono_s"] for r in ok if r.get("uptime_mono_s") is not None]
    return {
        "attempts": len(recs),
        "ok": len(ok),
        "errors": len(recs) - len(ok),
        "throttled": sum(1 for r in recs if r.get("throttled")),
        "p50_ms": pct(lat, 50),
        "p75_ms": pct(lat, 75),
        "p90_ms": pct(lat, 90),
        "p99_ms": pct(lat, 99),
        "min_ms": round(min(lat), 1) if lat else None,
        "max_ms": round(max(lat), 1) if lat else None,
        "mean_ms": round(statistics.fmean(lat), 1) if lat else None,
        "cold_flag_true": sum(1 for r in ok if r.get("cold_start") is True),
        # Snapshot evidence: one boot_id across many sessions means every
        # instance restored the same prepared environment.
        "distinct_boot_ids": len(boots),
        "distinct_req_ids": len(set(reqs)),
        "uptime_wall_s_median": round(statistics.median(wall), 1) if wall else None,
        "uptime_mono_s_median": round(statistics.median(mono), 3) if mono else None,
        "handler_ms_p75": pct([r["handler_ms"] for r in ok if r.get("handler_ms")], 75),
    }


def load_state() -> dict:
    if not C.STATE_FILE.exists():
        sys.exit(f"missing {C.STATE_FILE}; run scripts/deploy.py first")
    return json.loads(C.STATE_FILE.read_text())


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def iter_legs(state, sizes, versions, gap_s):
    """Yield (name, arn) for each leg, V1/V2 interleaved per size.

    gap_s > 0 sleeps between legs. Vended metrics are batched per minute, so a
    gap longer than a minute keeps each leg in its own buckets and lets
    overhead.py read per-leg statistics. It also lets V1's pre-initialized
    capacity refill between legs, as it did between the separately launched
    scenarios of the first (Tokyo) round.
    """
    first = True
    for size in sizes:
        for version in versions:
            name = C.runtime_name(size, version)
            if name not in state:
                continue
            if not first and gap_s > 0:
                print(f"[bench] quiet gap {gap_s:.0f}s")
                time.sleep(gap_s)
            first = False
            yield name, state[name]["arn"]


def run_cold(state, n, concurrency, sizes, versions=C.PLATFORM_VERSIONS, gap_s=0.0):
    client = C.data_client(max_pool=max(concurrency * 2, 20))
    out = {}
    # Interleave V1/V2 per size so both legs see the same service conditions.
    for name, arn in iter_legs(state, sizes, versions, gap_s):
        leg_start = utcnow()
        print(f"[cold] {name}: {n} fresh sessions, concurrency {concurrency}")
        t0 = time.perf_counter()
        recs = []
        with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
            futs = [ex.submit(cold_one, client, arn, i) for i in range(n)]
            for f in cf.as_completed(futs):
                recs.append(f.result())
        wall = time.perf_counter() - t0
        s = summarize(recs)
        s["wall_s"] = round(wall, 1)
        out[name] = {"summary": s, "records": recs,
                     "leg_start_utc": leg_start, "leg_end_utc": utcnow()}
        print(
            f"[cold]   p50={s['p50_ms']} p75={s['p75_ms']} p99={s['p99_ms']} ms | "
            f"ok={s['ok']}/{s['attempts']} | boot_ids={s['distinct_boot_ids']} | "
            f"wall={s['wall_s']}s"
        )
    return out


def run_burst(state, n, sizes, versions=C.PLATFORM_VERSIONS, gap_s=0.0):
    client = C.data_client(max_pool=n + 20)
    out = {}
    for name, arn in iter_legs(state, sizes, versions, gap_s):
        leg_start = utcnow()
        print(f"[burst] {name}: {n} simultaneous cold sessions")
        # Pre-warm the connection pool so TLS setup is not counted as start
        # time, then release the barrier so all N invokes leave together.
        ready = cf.ThreadPoolExecutor(max_workers=n)
        t0 = time.perf_counter()
        futs = [ready.submit(cold_one, client, arn, i) for i in range(n)]
        recs = [f.result() for f in futs]
        ready.shutdown()
        wall = time.perf_counter() - t0
        s = summarize(recs)
        s["wall_s"] = round(wall, 1)
        out[name] = {"summary": s, "records": recs,
                     "leg_start_utc": leg_start, "leg_end_utc": utcnow()}
        print(
            f"[burst]   p50={s['p50_ms']} p75={s['p75_ms']} p99={s['p99_ms']} ms | "
            f"ok={s['ok']}/{s['attempts']} throttled={s['throttled']} | "
            f"boot_ids={s['distinct_boot_ids']} | wall={s['wall_s']}s"
        )
    return out


def run_warm(state, n, sizes, versions=C.PLATFORM_VERSIONS, gap_s=0.0):
    client = C.data_client(max_pool=20)
    out = {}
    for name, arn in iter_legs(state, sizes, versions, gap_s):
        leg_start = utcnow()
        sid = new_session_id()
        print(f"[warm] {name}: 1 cold + {n} warm invokes on one session")
        first = invoke_once(client, arn, sid, 0)
        recs = [invoke_once(client, arn, sid, i + 1) for i in range(n)]
        stop_session(client, arn, sid)
        s = summarize(recs)
        s["cold_first_ms"] = first.get("latency_ms")
        out[name] = {"summary": s, "records": recs, "first": first,
                     "leg_start_utc": leg_start, "leg_end_utc": utcnow()}
        print(
            f"[warm]   cold_first={s['cold_first_ms']}ms "
            f"warm p50={s['p50_ms']} p75={s['p75_ms']} p99={s['p99_ms']} ms | "
            f"handler_p75={s['handler_ms_p75']}ms"
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["cold", "burst", "warm"])
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--sizes", default=",".join(C.IMAGE_SIZES))
    ap.add_argument("--versions", default=",".join(C.PLATFORM_VERSIONS))
    ap.add_argument("--gap", type=float, default=0.0, help="seconds between legs")
    args = ap.parse_args()

    state = load_state()
    sizes = [s for s in args.sizes.split(",") if s]
    versions = tuple(v for v in args.versions.split(",") if v)
    defaults = {"cold": 30, "burst": 50, "warm": 30}
    n = args.n if args.n is not None else defaults[args.scenario]

    started = datetime.now(timezone.utc).isoformat()
    rtt = measure_baseline_rtt(f"bedrock-agentcore.{C.REGION}.amazonaws.com")
    print(f"[rtt] {rtt}")

    if args.scenario == "cold":
        results = run_cold(state, n, args.concurrency, sizes, versions, args.gap)
    elif args.scenario == "burst":
        results = run_burst(state, n, sizes, versions, args.gap)
    else:
        results = run_warm(state, n, sizes, versions, args.gap)

    doc = {
        "scenario": args.scenario,
        "region": C.REGION,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "n": n,
        "concurrency": args.concurrency if args.scenario == "cold" else n,
        "gap_s": args.gap,
        "versions": list(versions),
        "baseline_rtt": rtt,
        "runtimes": {k: {kk: vv for kk, vv in v.items() if kk != "arn"} for k, v in state.items()},
        "results": results,
    }
    path = C.RESULTS_DIR / f"bench-{args.scenario}.json"
    path.write_text(json.dumps(doc, indent=2))
    print(f"[bench] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
