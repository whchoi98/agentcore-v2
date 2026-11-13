#!/usr/bin/env python3
"""Render V1-vs-V2 comparison tables from the results/*.json files.

Reads only local JSON; makes no AWS calls.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402

SIZES = list(C.IMAGE_SIZES)


def load(name):
    p = C.RESULTS_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def table(title, header, rows):
    print(f"\n## {title}")
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    line = "  ".join(h.ljust(w) for h, w in zip(header, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


def latency_rows(doc, key="p75_ms"):
    rows = []
    for size in SIZES:
        v1 = doc["results"].get(C.runtime_name(size, "V1"), {}).get("summary", {})
        v2 = doc["results"].get(C.runtime_name(size, "V2"), {}).get("summary", {})
        a, b = v1.get(key), v2.get(key)
        ratio = f"{a / b:.1f}x" if a and b else "-"
        rows.append([size, f"{a/1000:.2f}" if a else "-", f"{b/1000:.2f}" if b else "-", ratio])
    return rows


def main() -> int:
    deploy = load("runtimes.json")
    cold = load("bench-cold.json")
    burst = load("bench-burst.json")
    warm = load("bench-warm.json")
    usage = load("usage.json")
    mem = load("mem_usage.json")
    memrun = load("mem_runs.json")

    if deploy:
        table(
            "Deployment: time to READY",
            ["runtime", "platformVersion", "api call (s)", "READY (s)"],
            [
                [k, v["platform_version"], v["api_call_s"], v["ready_s"]]
                for k, v in sorted(deploy.items())
            ],
        )

    for label, doc in (("Cold start", cold), ("Burst (simultaneous cold sessions)", burst)):
        if not doc:
            continue
        n = doc["n"]
        conc = doc["concurrency"]
        table(
            f"{label} p75, seconds (n={n}/runtime, concurrency={conc})",
            ["image", "V1", "V2", "V1/V2"],
            latency_rows(doc, "p75_ms"),
        )
        rows = []
        for size in SIZES:
            for ver in ("V1", "V2"):
                s = doc["results"].get(C.runtime_name(size, ver), {}).get("summary")
                if not s:
                    continue
                rows.append(
                    [
                        size,
                        ver,
                        s["p50_ms"],
                        s["p75_ms"],
                        s["p99_ms"],
                        s["max_ms"],
                        f"{s['ok']}/{s['attempts']}",
                        s["throttled"],
                        s["distinct_boot_ids"],
                        s["uptime_mono_s_median"],
                        s["uptime_wall_s_median"],
                    ]
                )
        table(
            f"{label}: full distribution and snapshot evidence",
            [
                "image", "ver", "p50ms", "p75ms", "p99ms", "maxms",
                "ok", "thr", "boot_ids", "mono_s", "wall_s",
            ],
            rows,
        )

    if warm:
        rows = []
        for size in SIZES:
            for ver in ("V1", "V2"):
                s = warm["results"].get(C.runtime_name(size, ver), {}).get("summary")
                if not s:
                    continue
                rows.append(
                    [size, ver, s["cold_first_ms"], s["p50_ms"], s["p75_ms"], s["p99_ms"],
                     s["handler_ms_p75"]]
                )
        table(
            f"Warm latency on a reused session (n={warm['n']})",
            ["image", "ver", "first(cold)ms", "p50ms", "p75ms", "p99ms", "handler_p75ms"],
            rows,
        )

    if usage:
        rows = []
        for size in SIZES:
            for ver in ("V1", "V2"):
                r = next(
                    (x for x in usage["rows"] if x["size"] == size and x["version"] == ver), None
                )
                if not r:
                    continue
                rows.append(
                    [size, ver, r["sessions"], r["gb_hours"], r["vcpu_hours"],
                     r["implied_footprint_gb"], r["cost_total_usd"]]
                )
        table(
            "Billed usage for the identical benchmark workload",
            ["image", "ver", "sessions", "GB-hours", "vCPU-hours", "footprint GB", "cost USD"],
            rows,
        )
        print(f"\nexperiment total: ${usage['experiment_total_usd']:.2f}")

    if mem and memrun:
        table(
            f"Elastic memory: {memrun['alloc_mb']} MB spike then {memrun['idle_s']}s idle "
            f"(n={memrun['reps']} sessions/leg)",
            ["leg", "ver", "sessions", "sess-h", "GB-hours", "footprint GB",
             "median invoke ms", "mem cost USD"],
            [
                [r["leg"], r["version"], r["sessions"], r["session_hours"], r["gb_hours"],
                 r["implied_footprint_gb"], r["median_invoke_ms"], r["cost_memory_usd"]]
                for r in mem["rows"]
            ],
        )
        table(
            "Elastic memory: what the spike costs after it is released",
            ["ver", "control GB", "alloc GB", "spike adds GB", "GB-h ratio"],
            [
                [ver, d["control_footprint_gb"], d["alloc_footprint_gb"],
                 d["spike_attributable_gb"], f"{d['alloc_vs_control_gbh_ratio']}x"]
                for ver, d in mem["deltas"].items()
            ],
        )
        # Isolate the allocation work itself by subtracting the control leg,
        # which carries the same start cost but does no allocation.
        rows = []
        for ver, d in mem["deltas"].items():
            a = next(r for r in mem["rows"] if r["version"] == ver and r["condition"] == "alloc")
            c = next(r for r in mem["rows"] if r["version"] == ver and r["condition"] == "control")
            hold_ms = 2000
            rows.append(
                [ver, c["median_invoke_ms"], a["median_invoke_ms"],
                 round(a["median_invoke_ms"] - c["median_invoke_ms"] - hold_ms, 0)]
            )
        table(
            f"Elastic memory: time to allocate and touch {memrun['alloc_mb']} MB "
            "(control subtracted, 2000ms hold removed)",
            ["ver", "control invoke ms", "alloc invoke ms", "allocation work ms"],
            rows,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
