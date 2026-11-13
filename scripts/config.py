"""Shared configuration for the AgentCore Runtime V1-vs-V2 benchmark."""

import os
import pathlib

import boto3
from botocore.config import Config

# The client runs in ap-northeast-2 (Seoul). The first round (2026-09-19) ran
# against ap-northeast-1 (Tokyo), the closest V2 region at the time, so every
# latency figure there carries a cross-region round trip. V2 reached Seoul on
# 2026-11-12; run with BENCH_REGION=ap-northeast-2 for a same-region round.
# measure_baseline_rtt() reports the path cost either way.
REGION = os.environ.get("BENCH_REGION", "ap-northeast-1")

# When set, V2 runtimes are created WITHOUT the platformVersion field, relying
# on the service default (V2 became the default for new runtimes on
# 2026-11-12). get_agent_runtime still verifies what was actually applied.
OMIT_V2_PLATFORM_FIELD = os.environ.get("BENCH_V2_USE_DEFAULT", "") == "1"

ECR_REPOSITORY = os.environ.get("BENCH_ECR_REPO", "agentcore-v2-bench-agent")
ROLE_NAME = os.environ.get("BENCH_ROLE_NAME", "AgentCoreV2BenchExecutionRole")
RUNTIME_PREFIX = os.environ.get("BENCH_RUNTIME_PREFIX", "acbench")

# Image size label -> MB of incompressible padding added on top of the unpadded
# image. Same mapping as the AWS sample so results are comparable with the
# published figures. The unpadded image measures ~230 MB, hence the "200mb"
# label being approximate.
IMAGE_SIZES = {
    "200mb": 0,
    "1gb": 797,
    "2gb": 1821,
}

PLATFORM_VERSIONS = ("V1", "V2")

# Short session lifetimes: a benchmark session does one invoke and then idles,
# and AgentCore bills the whole session lifecycle, so a long idle timeout is
# pure waste here. 60s is the API minimum for both fields.
IDLE_TIMEOUT_S = int(os.environ.get("BENCH_IDLE_TIMEOUT", "60"))
MAX_LIFETIME_S = int(os.environ.get("BENCH_MAX_LIFETIME", "60"))

# Published AgentCore Runtime microVM rates (USD), used for the cost model.
RATES = {
    "V1": {"vcpu_hour": 0.0895, "gb_hour": 0.00945},
    "V2": {"vcpu_hour": 0.1276, "gb_hour": 0.0169},
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Separate directory per round so a new round never overwrites the evidence of
# an earlier one (results/ holds the Tokyo round).
RESULTS_DIR = ROOT / os.environ.get("BENCH_RESULTS_DIR", "results")
RESULTS_DIR.mkdir(exist_ok=True)
STATE_FILE = RESULTS_DIR / "runtimes.json"


def runtime_name(size: str, version: str) -> str:
    """Runtime names allow [a-zA-Z0-9_] only, so no hyphens."""
    return f"{RUNTIME_PREFIX}_{size}_{version}"


def platform_kwargs(version: str) -> dict:
    """platformVersion argument for create/update, or {} to use the default."""
    if version == "V2" and OMIT_V2_PLATFORM_FIELD:
        return {}
    return {"platformVersion": version}


def control_client():
    return boto3.client(
        "bedrock-agentcore-control",
        region_name=REGION,
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}),
    )


def data_client(max_pool: int = 200, read_timeout: int = 120):
    return boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        config=Config(
            max_pool_connections=max_pool,
            read_timeout=read_timeout,
            connect_timeout=15,
            # Cold-start latency must be measured, not retried away: a retry
            # would hide the very thing under test behind a second attempt.
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )


def account_id() -> str:
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def image_uri(size: str, acct: str) -> str:
    return f"{acct}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPOSITORY}:{size}"
