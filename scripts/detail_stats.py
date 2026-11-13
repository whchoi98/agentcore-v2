#!/usr/bin/env python3
"""Extract the detailed statistics the report needs from results/*.json.

Everything here is derived from the raw per-invocation records, so the report
can quote distributions, bimodality, consistency bands and cost projections
without re-running anything against AWS.

Usage:
  python scripts/detail_stats.py            # human-readable
  python scripts/detail_stats.py --json     # machine-readable
"""

import argparse
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402

SIZES = list(C.IMAGE_SIZES)
PCTS = (0, 10, 25, 50, 75, 90, 95, 99, 100)


def load(name):
    p = C.RESULTS_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def dist(lat: list[float]) -> dict:
    """Full distribution plus the spread measures that matter for this comparison."""
    if not lat:
        return {}
    mean = statistics.fmean(lat)
    sd = statistics.pstdev(lat) if len(lat) > 1 else 0.0
    return {
        "n": len(lat),
        "percentiles_ms": {f"p{p}": round(pct(lat, p), 1) for p in PCTS},
        "mean_ms": round(mean, 1),
        "stdev_ms": round(sd, 1),
        # Coefficient of variation: the single clearest number for
        # "consistent cold starts", since it is scale-free.
        "cv": round(sd / mean, 3) if mean else None,
        # Absolute width of the band the measurements fall in.
        "band_ms": round(max(lat) - min(lat), 1),
        "p99_over_p50": round(pct(lat, 99) / pct(lat, 50), 2) if pct(lat, 50) else None,
    }


def bimodality(lat: list[float], split_ratio: float = 2.0) -> dict:
    """Split a distribution at the largest gap and describe the two clusters.

    V1's cold starts are bimodal: some sessions land on an already-initialized
    environment and return fast, the rest pay a full cold start. Reporting only
    a percentile hides that, so find the gap and size each cluster.
    """
    if len(lat) < 4:
        return {}
    s = sorted(lat)
    gaps = [(s[i + 1] - s[i], i) for i in range(len(s) - 1)]
    gap, idx = max(gaps)
    lo, hi = s[: idx + 1], s[idx + 1 :]
    # Only call it bimodal if the clusters are separated by a real factor.
    is_bimodal = bool(lo and hi and statistics.fmean(hi) / statistics.fmean(lo) >= split_ratio)
    return {
        "is_bimodal": is_bimodal,
        "gap_ms": round(gap, 1),
        "fast_cluster": {
            "n": len(lo),
            "share": round(len(lo) / len(s), 3),
            "median_ms": round(statistics.median(lo), 1),
        },
        "slow_cluster": {
            "n": len(hi),
            "share": round(len(hi) / len(s), 3),
            "median_ms": round(statistics.median(hi), 1),
        },
    }


def histogram(lat: list[float], buckets: int = 12, width: int = 40) -> list[str]:
    """Coarse ASCII histogram, for showing distribution shape in the report."""
    if not lat:
        return []
    lo, hi = min(lat), max(lat)
    if hi == lo:
        return [f"{lo/1000:7.2f}s |{'#' * width} {len(lat)}"]
    step = (hi - lo) / buckets
    rows = []
    counts = [0] * buckets
    for v in lat:
        i = min(buckets - 1, int((v - lo) / step))
        counts[i] += 1
    peak = max(counts) or 1
    for i, c in enumerate(counts):
        if c == 0:
            continue
        edge = lo + i * step
        bar = "#" * max(1, round(c / peak * width))
        rows.append(f"{edge/1000:7.2f}s |{bar} {c}")
    return rows


def boot_id_detail(recs: list[dict]) -> dict:
    """How many sessions shared each process identity."""
    counts: dict[str, int] = {}
    for r in recs:
        if r.get("ok") and r.get("boot_id"):
            counts[r["boot_id"]] = counts.get(r["boot_id"], 0) + 1
    return {
        "distinct": len(counts),
        "sessions": sum(counts.values()),
        "sessions_per_boot_id": sorted(counts.values(), reverse=True),
        "max_shared": max(counts.values()) if counts else 0,
    }


def ramp_drift(recs: list[dict], bucket: int = 10) -> list[dict]:
    """p75 by arrival order, to show whether latency drifts during a ramp."""
    ordered = [r for r in sorted(recs, key=lambda x: x["seq"]) if r.get("ok")]
    out = []
    for i in range(0, len(ordered), bucket):
        chunk = [r["latency_ms"] for r in ordered[i : i + bucket]]
        if chunk:
            out.append({"seq_range": f"{i}-{i+len(chunk)-1}", "p75_ms": round(pct(chunk, 75), 1)})
    return out


def cost_projection(usage: dict) -> list[dict]:
    """Extrapolate the measured per-session usage to a larger session count.

    Uses the measured GB-hours and vCPU-hours per session from the identical
    81-session workload, so the projection carries the same session-lifetime
    assumptions as the measurement -- it is a comparison between V1 and V2 on
    equal terms, not a forecast of anybody's production bill.
    """
    rows = []
    for r in usage["rows"]:
        n = r["sessions"]
        if not n:
            continue
        rate = C.RATES[r["version"]]
        per = (r["gb_hours"] / n) * rate["gb_hour"] + (r["vcpu_hours"] / n) * rate["vcpu_hour"]
        rows.append(
            {
                "size": r["size"],
                "version": r["version"],
                "gb_hours_per_session": round(r["gb_hours"] / n, 6),
                "vcpu_hours_per_session": round(r["vcpu_hours"] / n, 6),
                "usd_per_session": round(per, 6),
                "usd_per_1k_sessions": round(per * 1000, 3),
                "usd_per_100k_sessions": round(per * 100_000, 1),
            }
        )
    return rows


def build() -> dict:
    cold, burst, warm = load("bench-cold.json"), load("bench-burst.json"), load("bench-warm.json")
    usage, mem, memrun = load("usage.json"), load("mem_usage.json"), load("mem_runs.json")
    deploy = load("runtimes.json")

    doc = {"scenarios": {}, "deploy": deploy}
    for tag, src in (("cold", cold), ("burst", burst), ("warm", warm)):
        if not src:
            continue
        doc["scenarios"][tag] = {"n": src["n"], "baseline_rtt": src["baseline_rtt"], "runtimes": {}}
        for name, res in src["results"].items():
            recs = res["records"]
            lat = [r["latency_ms"] for r in recs if r.get("ok")]
            entry = {
                "distribution": dist(lat),
                "boot_ids": boot_id_detail(recs),
                "histogram": histogram(lat),
                "errors": [r.get("error") for r in recs if not r.get("ok")],
            }
            if tag != "warm":
                entry["bimodality"] = bimodality(lat)
                entry["ramp_drift"] = ramp_drift(recs)
            else:
                entry["cold_first_ms"] = res["first"].get("latency_ms")
            ok = [r for r in recs if r.get("ok")]
            entry["uptime_mono_s"] = {
                "min": min((r["uptime_mono_s"] for r in ok if r.get("uptime_mono_s")), default=None),
                "max": max((r["uptime_mono_s"] for r in ok if r.get("uptime_mono_s")), default=None),
            }
            entry["uptime_wall_s"] = {
                "min": min((r["uptime_wall_s"] for r in ok if r.get("uptime_wall_s")), default=None),
                "max": max((r["uptime_wall_s"] for r in ok if r.get("uptime_wall_s")), default=None),
            }
            doc["scenarios"][tag]["runtimes"][name] = entry

    if usage:
        doc["usage"] = usage
        doc["cost_projection"] = cost_projection(usage)
    if mem:
        doc["memory"] = mem
    if memrun:
        doc["memory_run"] = {
            "alloc_mb": memrun["alloc_mb"],
            "idle_s": memrun["idle_s"],
            "reps": memrun["reps"],
            "leg_windows": memrun["leg_windows"],
            "rss_profile": next(
                (
                    r["memory_profile"]
                    for leg in memrun["legs"].values()
                    for r in leg
                    if r.get("memory_profile")
                ),
                None,
            ),
            "invoke_ms": {k: [r["invoke_ms"] for r in v] for k, v in memrun["legs"].items()},
        }
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    doc = build()
    out = C.RESULTS_DIR / "detail_stats.json"
    out.write_text(json.dumps(doc, indent=2))
    if a.json:
        print(json.dumps(doc, indent=2))
        return 0

    for tag, sc in doc["scenarios"].items():
        print(f"\n{'='*78}\n{tag.upper()}  (n={sc['n']}/runtime)\n{'='*78}")
        for size in SIZES:
            for ver in C.PLATFORM_VERSIONS:
                name = C.runtime_name(size, ver)
                e = sc["runtimes"].get(name)
                if not e:
                    continue
                d = e["distribution"]
                print(f"\n-- {name}")
                print(f"   {d['percentiles_ms']}")
                print(
                    f"   mean={d['mean_ms']} sd={d['stdev_ms']} cv={d['cv']} "
                    f"band={d['band_ms']}ms p99/p50={d['p99_over_p50']}"
                )
                print(f"   boot_ids={e['boot_ids']}")
                if e.get("bimodality", {}).get("is_bimodal"):
                    b = e["bimodality"]
                    print(
                        f"   BIMODAL gap={b['gap_ms']}ms  "
                        f"fast {b['fast_cluster']['n']} @ {b['fast_cluster']['median_ms']}ms / "
                        f"slow {b['slow_cluster']['n']} @ {b['slow_cluster']['median_ms']}ms"
                    )
                for row in e["histogram"]:
                    print("      " + row)

    if "cost_projection" in doc:
        print(f"\n{'='*78}\nCOST PROJECTION (measured per-session usage)\n{'='*78}")
        for r in doc["cost_projection"]:
            print(
                f"  {r['size']:>6} {r['version']}  {r['gb_hours_per_session']:.6f} GB-h/sess  "
                f"${r['usd_per_1k_sessions']:.3f}/1k  ${r['usd_per_100k_sessions']:.1f}/100k"
            )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
