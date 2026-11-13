#!/usr/bin/env python3
"""Probe how platformVersion behaves now that V2 is the default.

On 2026-11-12 AWS announced that new AgentCore runtimes use the next
generation runtime (platform version V2) by default in 19 regions, Seoul
included, and that existing runtimes stay on their current version until moved.
The developer guide still said "V1 is the default" on 2026-11-13, so this
script asks the API directly instead of trusting either text.

Cases (each runtime uses the 200mb echo image and is deleted at the end):

  default    create with NO platformVersion          -> which version?
  v1         create with platformVersion=V1          -> V1 still selectable?
  keep       update the v1 runtime, field omitted    -> stays V1?
  migrate    update the v1 runtime to V2             -> time to READY, works?
  rollback   update the default runtime to V1        -> can go back?
  envlimit   create V2 with 3.5 KB of env variables  -> 4 KB limit live?

The label from get_agent_runtime is not taken on faith: each runtime is invoked
on a few fresh sessions, and the echo agent's boot_id / uptime_mono_s show
whether instances restored one snapshot (V2) or booted their own process (V1).

Usage:
  python scripts/default_probe.py [--cases default,v1,keep,migrate,rollback,envlimit]
                                 [--keep-runtimes] [--suffix=-rerun]
"""

import argparse
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench as B  # noqa: E402
import config as C  # noqa: E402
import deploy as D  # noqa: E402

PREFIX = "acprobe"
ALL_CASES = ("default", "v1", "keep", "migrate", "rollback", "envlimit")

# V2 container agents were limited to 2.5 KB of environment variables at launch;
# the October 2026 release notes raise it to 4 KB (the V1 limit). 3.5 KB sits
# between the two, so creation succeeding means the new limit is live.
ENV_PROBE_BYTES = 3584


def base_config(role_arn: str, uri: str, step: str) -> dict:
    return dict(
        roleArn=role_arn,
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": uri}},
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
        lifecycleConfiguration={"idleRuntimeSessionTimeout": 60, "maxLifetime": 60},
        # PROBE_STEP changes on every update so each update is a real new
        # runtime version, not a no-op.
        environmentVariables={"IMAGE_SIZE_LABEL": "200mb", "PROBE_STEP": step},
    )


def snapshot_evidence(arn: str, n: int = 3) -> dict:
    """Invoke n fresh sessions sequentially and summarise the identity fields."""
    client = C.data_client(max_pool=10)
    recs = [B.cold_one(client, arn, i) for i in range(n)]
    ok = [r for r in recs if r.get("ok")]
    return {
        "sessions": n,
        "ok": len(ok),
        "errors": sorted({r.get("error") for r in recs if not r.get("ok")} - {None}),
        "latency_ms": [r["latency_ms"] for r in recs],
        "distinct_boot_ids": len({r.get("boot_id") for r in ok}),
        "uptime_mono_s": [r.get("uptime_mono_s") for r in ok],
        "uptime_wall_s": [r.get("uptime_wall_s") for r in ok],
    }


def describe(ctl, rid: str) -> dict:
    g = ctl.get_agent_runtime(agentRuntimeId=rid)
    return {
        "status": g["status"],
        "platformVersion": g.get("platformVersion"),
        "agentRuntimeVersion": g.get("agentRuntimeVersion"),
        "failureReason": g.get("failureReason"),
    }


def step(ctl, label: str, call, rid_from_resp=None) -> dict:
    """Run a create/update call, wait for a terminal state, record everything."""
    t0 = time.perf_counter()
    resp = call()
    api_s = time.perf_counter() - t0
    rid = rid_from_resp(resp) if rid_from_resp else resp["agentRuntimeId"]
    status, ready_s = D.wait_ready(ctl, rid)
    rec = {
        "step": label,
        "runtime_id": rid,
        "api_call_s": round(api_s, 2),
        "ready_s": round(ready_s, 1),
        "terminal_status": status,
        # Does the write response itself carry platformVersion? (It did not
        # in September.)
        "response_keys": sorted(k for k in resp if k != "ResponseMetadata"),
        "response_platformVersion": resp.get("platformVersion"),
        "after": describe(ctl, rid),
    }
    print(
        f"[probe] {label}: {status} in {ready_s:.1f}s -> "
        f"platformVersion={rec['after']['platformVersion']} "
        f"version={rec['after']['agentRuntimeVersion']}"
    )
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=",".join(ALL_CASES))
    ap.add_argument("--keep-runtimes", action="store_true")
    ap.add_argument("--suffix", default="", help="appended to the output file name")
    a = ap.parse_args()
    cases = [c for c in a.cases.split(",") if c]
    unknown = set(cases) - set(ALL_CASES)
    if unknown:
        sys.exit(f"unknown cases: {sorted(unknown)}")

    acct = C.account_id()
    role_arn = D.ensure_role(acct)
    ctl = C.control_client()
    uri = C.image_uri("200mb", acct)
    tag = C.REGION.replace("-", "")

    doc = {
        "region": C.REGION,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "botocore": __import__("botocore").__version__,
        "image_uri": uri,
        "steps": [],
        "evidence": {},
    }
    out = C.RESULTS_DIR / f"default_probe-{C.REGION}{a.suffix}.json"

    def save():
        out.write_text(json.dumps(doc, indent=2, default=str))

    created = {}
    try:
        if "default" in cases or "rollback" in cases:
            name = f"{PREFIX}_default_{tag}"
            rec = step(
                ctl,
                "create default (platformVersion omitted)",
                lambda: ctl.create_agent_runtime(
                    agentRuntimeName=name, **base_config(role_arn, uri, "1")
                ),
            )
            created["default"] = rec["runtime_id"]
            doc["steps"].append(rec)
            save()
            arn = ctl.get_agent_runtime(agentRuntimeId=rec["runtime_id"])["agentRuntimeArn"]
            doc["evidence"]["default"] = snapshot_evidence(arn)
            print(f"[probe]   evidence: {doc['evidence']['default']}")
            save()

        if {"v1", "keep", "migrate"} & set(cases):
            name = f"{PREFIX}_v1_{tag}"
            rec = step(
                ctl,
                "create explicit V1",
                lambda: ctl.create_agent_runtime(
                    agentRuntimeName=name,
                    platformVersion="V1",
                    **base_config(role_arn, uri, "1"),
                ),
            )
            created["v1"] = rec["runtime_id"]
            doc["steps"].append(rec)
            save()
            arn = ctl.get_agent_runtime(agentRuntimeId=rec["runtime_id"])["agentRuntimeArn"]
            doc["evidence"]["v1"] = snapshot_evidence(arn)
            print(f"[probe]   evidence: {doc['evidence']['v1']}")
            save()

        if "keep" in cases:
            rid = created["v1"]
            rec = step(
                ctl,
                "update V1 runtime, platformVersion omitted",
                lambda: ctl.update_agent_runtime(
                    agentRuntimeId=rid, **base_config(role_arn, uri, "2")
                ),
            )
            doc["steps"].append(rec)
            save()

        if "migrate" in cases:
            rid = created["v1"]
            rec = step(
                ctl,
                "update V1 runtime to platformVersion=V2",
                lambda: ctl.update_agent_runtime(
                    agentRuntimeId=rid, platformVersion="V2", **base_config(role_arn, uri, "3")
                ),
            )
            doc["steps"].append(rec)
            save()
            arn = ctl.get_agent_runtime(agentRuntimeId=rid)["agentRuntimeArn"]
            doc["evidence"]["migrate"] = snapshot_evidence(arn)
            print(f"[probe]   evidence: {doc['evidence']['migrate']}")
            save()

        if "rollback" in cases:
            rid = created["default"]
            rec = step(
                ctl,
                "update default runtime to platformVersion=V1",
                lambda: ctl.update_agent_runtime(
                    agentRuntimeId=rid, platformVersion="V1", **base_config(role_arn, uri, "2")
                ),
            )
            doc["steps"].append(rec)
            save()
            arn = ctl.get_agent_runtime(agentRuntimeId=rid)["agentRuntimeArn"]
            doc["evidence"]["rollback"] = snapshot_evidence(arn)
            print(f"[probe]   evidence: {doc['evidence']['rollback']}")
            save()

        if "envlimit" in cases:
            name = f"{PREFIX}_env_{tag}"
            cfg = base_config(role_arn, uri, "1")
            used = sum(len(k) + len(v) for k, v in cfg["environmentVariables"].items())
            cfg["environmentVariables"]["PAD"] = "x" * (ENV_PROBE_BYTES - used - len("PAD"))
            total = sum(len(k) + len(v) for k, v in cfg["environmentVariables"].items())
            try:
                rec = step(
                    ctl,
                    f"create V2 with {total} B of environment variables",
                    lambda: ctl.create_agent_runtime(
                        agentRuntimeName=name, platformVersion="V2", **cfg
                    ),
                )
                created["envlimit"] = rec["runtime_id"]
                rec["env_bytes"] = total
            except Exception as e:  # noqa: BLE001 - the rejection is the result
                rec = {
                    "step": f"create V2 with {total} B of environment variables",
                    "env_bytes": total,
                    "rejected": f"{type(e).__name__}: {e}"[:400],
                }
                print(f"[probe] envlimit rejected: {rec['rejected']}")
            doc["steps"].append(rec)
            save()

        # Does the list view expose the platform version?
        listed = []
        for page in ctl.get_paginator("list_agent_runtimes").paginate():
            for rt in page.get("agentRuntimes", []):
                if rt["agentRuntimeName"].startswith(PREFIX):
                    listed.append({k: v for k, v in rt.items()})
        doc["list_agent_runtimes_items"] = listed
    finally:
        doc["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if not a.keep_runtimes:
            for key, rid in created.items():
                try:
                    D.wait_ready(ctl, rid, timeout_s=900)
                    ctl.delete_agent_runtime(agentRuntimeId=rid)
                    print(f"[probe] deleted {key} runtime {rid}")
                except Exception as e:  # noqa: BLE001 - report and continue
                    print(f"[probe] delete {rid} failed: {e}")
        doc["deleted"] = not a.keep_runtimes
        save()
        print(f"[probe] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
