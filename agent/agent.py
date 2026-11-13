"""Echo agent for AgentCore Runtime V1-vs-V2 benchmarking.

Implements the AgentCore Runtime HTTP service contract:
  POST /invocations -> echoes the request plus diagnostic metadata
  GET  /ping        -> health check (V2 snapshots on the first healthy ping)

No LLM call and no heavy dependencies, so measured latency reflects the
platform's start path rather than application work.

Snapshot diagnostics
--------------------
Everything named BOOT_* is computed once at import, i.e. *before* the V2
snapshot is taken, so every restored instance inherits the same values. That
is exactly what makes them useful as evidence:

  boot_id      random at import. On V1 each microVM runs its own process, so
               every cold session reports a different id. On V2 every instance
               restores the same snapshot, so they all report the SAME id.
  uptime_mono  time.monotonic() does not advance across a restore, so on V2
               this stays near the value it had when the snapshot was taken.
  uptime_wall  time.time() does advance, so on V2 this grows with the age of
               the snapshot -- minutes or hours, not the age of the instance.

Per-request values (req_id, served_at) are generated in the handler, which is
what the V2 optimization guidance requires: a value produced at startup is
frozen into the snapshot and would repeat across instances.
"""

import gc
import json
import os
import platform
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

# --- Startup context: captured before the V2 snapshot, shared by all restores.
BOOT_ID = os.urandom(8).hex()
BOOT_WALL = time.time()
BOOT_MONO = time.monotonic()
BOOT_PID = os.getpid()
IMAGE_SIZE_LABEL = os.environ.get("IMAGE_SIZE_LABEL", "unknown")
PLATFORM_VERSION_LABEL = os.environ.get("PLATFORM_VERSION_LABEL", "unknown")

_cold_lock = threading.Lock()
_cold_pending = True

app = FastAPI(title="AgentCore Runtime V1/V2 echo benchmark", version="1.0.0")


def _consume_cold_start() -> bool:
    """True only for the first invocation served by this instance."""
    global _cold_pending
    with _cold_lock:
        cold = _cold_pending
        _cold_pending = False
    return cold


def _rss_mb() -> float:
    """Resident set size of this process, in MB, from /proc."""
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as fh:
            pages = int(fh.read().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
    except OSError:
        return -1.0


def _alloc_then_free(mb: int, hold_s: float) -> dict[str, Any]:
    """Allocate mb of memory, touch every page, hold, then release it.

    This is the workload shape the V2 announcement describes: a session that
    spikes and then lets the memory go. V1 bills the peak for the rest of the
    session; V2 is supposed to reclaim it. Pages are written, not just
    reserved, so the memory is genuinely resident rather than lazily mapped.
    """
    rss_before = _rss_mb()
    chunk = bytearray(1024 * 1024)
    blocks = []
    for i in range(mb):
        b = bytearray(chunk)
        b[0] = i % 251  # write so the page is faulted in, not just mapped
        b[-1] = i % 251
        blocks.append(b)
    rss_peak = _rss_mb()
    time.sleep(hold_s)
    blocks.clear()
    del blocks
    gc.collect()
    time.sleep(0.2)
    return {
        "alloc_mb_requested": mb,
        "rss_before_mb": rss_before,
        "rss_peak_mb": rss_peak,
        "rss_after_free_mb": _rss_mb(),
        "hold_s": hold_s,
    }


@app.post("/invocations")
async def invocations(request: Request) -> dict[str, Any]:
    t0 = time.perf_counter()
    cold = _consume_cold_start()
    raw = await request.body()
    try:
        echo: Any = json.loads(raw) if raw else None
    except ValueError:
        echo = raw.decode("utf-8", "replace")

    # Optional memory-profile mode, used by the elastic-memory scenario.
    memory_profile = None
    if isinstance(echo, dict) and echo.get("mode") == "alloc":
        memory_profile = await run_in_threadpool(
            _alloc_then_free,
            int(echo.get("mb", 512)),
            float(echo.get("hold_s", 1.0)),
        )

    now_wall = time.time()
    body = {
        "echo": echo,
        "cold_start": cold,
        # Startup-scoped: identical across every V2 instance of one snapshot.
        "boot_id": BOOT_ID,
        "boot_pid": BOOT_PID,
        "boot_wall": round(BOOT_WALL, 3),
        "uptime_wall_s": round(now_wall - BOOT_WALL, 3),
        "uptime_mono_s": round(time.monotonic() - BOOT_MONO, 3),
        # Request-scoped: must be fresh per request on V2.
        "req_id": os.urandom(8).hex(),
        "served_at": datetime.fromtimestamp(now_wall, timezone.utc).isoformat(),
        "hostname": platform.node(),
        "rss_mb": _rss_mb(),
        "memory_profile": memory_profile,
        "image_size_label": IMAGE_SIZE_LABEL,
        "platform_version_label": PLATFORM_VERSION_LABEL,
    }
    body["handler_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return {"output": body}


@app.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
