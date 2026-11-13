#!/usr/bin/env python3
"""Compare benchmark rounds side by side (local JSON only, no AWS calls).

Each round lives in its own results directory written by the same scripts:

  results/               Tokyo, 2026-09-19 (client in Seoul, cross-region)
  results-seoul/         Seoul, 2026-11-13 (client in Seoul, same region)
  results-tokyo-1113/    Tokyo, 2026-11-13 same-day control (optional)

Printing Markdown tables keeps the output pasteable into the report.

Usage:
  python scripts/compare_rounds.py [--rounds results,results-seoul,results-tokyo-1113]
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config as C  # noqa: E402
import detail_stats as DS  # noqa: E402

SIZES = list(C.IMAGE_SIZES)
LABEL = {
    "results": "도쿄 9/19",
    "results-seoul": "서울 11/13",
    "results-tokyo-1113": "도쿄 11/13",
    "results-seoul-gap": "서울 11/13 반복(간격)",
    "results-tokyo-1113-gap": "도쿄 11/13 V2 반복(간격)",
}


def load(d: pathlib.Path, name: str):
    p = d / name
    return json.loads(p.read_text()) if p.exists() else None


def name(size, ver):
    return f"{C.RUNTIME_PREFIX}_{size}_{ver}"


def md(header, rows):
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join("---" if i < 2 else "---:" for i in range(len(header))) + "|")
    for r in rows:
        print("| " + " | ".join("-" if c is None else str(c) for c in r) + " |")
    print()


def fmt(v, nd=1):
    return None if v is None else f"{v:,.{nd}f}"


def lat_of(doc, rt):
    res = doc["results"].get(rt) if doc else None
    if not res:
        return []
    return [r["latency_ms"] for r in res["records"] if r.get("ok")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", default="results,results-seoul,results-tokyo-1113")
    a = ap.parse_args()
    rounds = [r for r in a.rounds.split(",") if (C.ROOT / r).exists()]
    data = {}
    for r in rounds:
        d = C.ROOT / r
        data[r] = {
            k: load(d, f)
            for k, f in (
                ("cold", "bench-cold.json"),
                ("burst", "bench-burst.json"),
                ("warm", "bench-warm.json"),
                ("deploy", "runtimes.json"),
                ("usage", "usage.json"),
                ("mem", "mem_usage.json"),
                ("memdeploy", "mem_runtimes.json"),
                ("overhead", "overhead.json"),
            )
        }

    print("## 네트워크 기준선 (TCP+TLS 중위값, ms)\n")
    md(
        ["시나리오"] + [LABEL.get(r, r) for r in rounds],
        [
            [s] + [
                fmt(data[r][s]["baseline_rtt"]["tcp_tls_ms_median"], 2) if data[r][s] else None
                for r in rounds
            ]
            for s in ("cold", "burst", "warm")
        ],
    )

    for scen in ("cold", "burst"):
        print(f"## {scen} p50 / p75 / CV\n")
        rows = []
        for size in SIZES:
            for ver in C.PLATFORM_VERSIONS:
                row = [size, ver]
                for r in rounds:
                    lat = lat_of(data[r][scen], name(size, ver))
                    dd = DS.dist(lat)
                    row.append(
                        f"{fmt(dd['percentiles_ms']['p50'])} / {fmt(dd['percentiles_ms']['p75'])}"
                        f" / {dd['cv']}"
                        if dd
                        else None
                    )
                rows.append(row)
        md(["이미지", "ver"] + [LABEL.get(r, r) for r in rounds], rows)

        print(f"## {scen} V1/V2 p75 배수\n")
        rows = []
        for size in SIZES:
            row = [size, ""]
            for r in rounds:
                v1 = DS.dist(lat_of(data[r][scen], name(size, "V1")))
                v2 = DS.dist(lat_of(data[r][scen], name(size, "V2")))
                row.append(
                    f"{v1['percentiles_ms']['p75'] / v2['percentiles_ms']['p75']:.1f}x"
                    if v1 and v2
                    else None
                )
            rows.append(row)
        md(["이미지", ""] + [LABEL.get(r, r) for r in rounds], rows)

        print(f"## {scen} V1 이봉성 (빠른 군집 n @ 중위값 / 느린 군집 n @ 중위값)\n")
        rows = []
        for size in SIZES:
            row = [size, "V1"]
            for r in rounds:
                b = DS.bimodality(lat_of(data[r][scen], name(size, "V1")))
                row.append(
                    f"{b['fast_cluster']['n']} @ {fmt(b['fast_cluster']['median_ms'],0)} / "
                    f"{b['slow_cluster']['n']} @ {fmt(b['slow_cluster']['median_ms'],0)}"
                    if b and b.get("is_bimodal")
                    else ("단봉" if b else None)
                )
            rows.append(row)
        md(["이미지", "ver"] + [LABEL.get(r, r) for r in rounds], rows)

        print(f"## {scen} V2 스냅샷 증거 (boot_id 수 / uptime_mono 중위값 s)\n")
        rows = []
        for size in SIZES:
            row = [size, "V2"]
            for r in rounds:
                doc = data[r][scen]
                s = doc["results"].get(name(size, "V2"), {}).get("summary") if doc else None
                row.append(
                    f"{s['distinct_boot_ids']} / {s['uptime_mono_s_median']}" if s else None
                )
            rows.append(row)
        md(["이미지", "ver"] + [LABEL.get(r, r) for r in rounds], rows)

    print("## warm p50 / p75 (ms)\n")
    rows = []
    for size in SIZES:
        for ver in C.PLATFORM_VERSIONS:
            row = [size, ver]
            for r in rounds:
                doc = data[r]["warm"]
                s = doc["results"].get(name(size, ver), {}).get("summary") if doc else None
                row.append(f"{fmt(s['p50_ms'])} / {fmt(s['p75_ms'])}" if s else None)
            rows.append(row)
    md(["이미지", "ver"] + [LABEL.get(r, r) for r in rounds], rows)

    print("## READY 도달 시간 (s)\n")
    rows = []
    for size in SIZES + ["mem"]:
        for ver in C.PLATFORM_VERSIONS:
            row = [size, ver]
            for r in rounds:
                dep = data[r]["deploy"] if size != "mem" else data[r]["memdeploy"]
                e = (dep or {}).get(name(size, ver))
                row.append(fmt(e["ready_s"]) if e else None)
            rows.append(row)
    md(["이미지", "ver"] + [LABEL.get(r, r) for r in rounds], rows)

    print("## 과금 GB-hours / vCPU-hours (81세션 동일 워크로드)\n")
    rows = []
    for size in SIZES:
        for ver in C.PLATFORM_VERSIONS:
            row = [size, ver]
            for r in rounds:
                u = data[r]["usage"]
                x = next(
                    (x for x in (u or {}).get("rows", []) if x["size"] == size and x["version"] == ver),
                    None,
                )
                row.append(f"{x['gb_hours']:.4f} / {x['vcpu_hours']:.4f}" if x else None)
            rows.append(row)
    md(["이미지", "ver"] + [LABEL.get(r, r) for r in rounds], rows)
    for r in rounds:
        u = data[r]["usage"]
        if u:
            print(f"- {LABEL.get(r, r)} 실험 합계: ${u['experiment_total_usd']:.4f}")
    print()

    print("## 탄력 메모리 (대조군 → 스파이크 후 footprint, 스파이크 기여분)\n")
    rows = []
    for ver in C.PLATFORM_VERSIONS:
        row = [ver, ""]
        for r in rounds:
            m = data[r]["mem"]
            dd = (m or {}).get("deltas", {}).get(ver)
            row.append(
                f"{dd['control_footprint_gb']} → {dd['alloc_footprint_gb']} GB "
                f"(+{dd['spike_attributable_gb']})"
                if dd
                else None
            )
        rows.append(row)
    md(["ver", ""] + [LABEL.get(r, r) for r in rounds], rows)

    if any(data[r]["overhead"] for r in rounds):
        print("## V2 OverheadLatency p50 vs 클라이언트 p50 (ms)\n")
        rows = []
        for scen in ("cold", "burst", "warm"):
            for size in SIZES:
                row = [scen, size]
                for r in rounds:
                    o = data[r]["overhead"]
                    x = next(
                        (
                            x
                            for x in (o or {}).get("rows", [])
                            if x["scenario"] == scen and x["runtime"] == name(size, "V2")
                        ),
                        None,
                    )
                    if x and x["OverheadLatency"]:
                        row.append(
                            f"{fmt(x['OverheadLatency'].get('p50'))} / {fmt(x['client_p50_ms'])}"
                        )
                    else:
                        row.append(None)
                rows.append(row)
        md(["시나리오", "이미지"] + [LABEL.get(r, r) for r in rounds], rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
