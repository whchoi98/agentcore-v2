#!/usr/bin/env python3
"""Create the execution role and the six agent runtimes (3 sizes x V1/V2).

Also measures how long each runtime takes to reach READY, which is itself a
V1-vs-V2 difference: V1 registers configuration and is ready in seconds, while
V2 has to boot the container, wait for a healthy /ping and capture a snapshot.

Writes results/runtimes.json for the benchmark and cleanup scripts.
"""

import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import config as C  # noqa: E402

TRUST = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AssumeRolePolicy",
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": None},  # filled in below
                "ArnLike": {"aws:SourceArn": None},
            },
        }
    ],
}


def permissions_policy(acct: str) -> dict:
    """Least-privilege execution policy per the AgentCore Runtime docs.

    The echo agent makes no Bedrock call, so bedrock:InvokeModel is omitted.
    """
    r = C.REGION
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ECRImageAccess",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": [f"arn:aws:ecr:{r}:{acct}:repository/{C.ECR_REPOSITORY}"],
            },
            {
                "Sid": "ECRTokenAccess",
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                "Resource": [
                    f"arn:aws:logs:{r}:{acct}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogGroups"],
                "Resource": [f"arn:aws:logs:{r}:{acct}:log-group:*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{r}:{acct}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                "Resource": ["*"],
            },
            {
                "Effect": "Allow",
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
            {
                "Sid": "GetAgentAccessToken",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{r}:{acct}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{r}:{acct}:workload-identity-directory/default/workload-identity/*",
                ],
            },
        ],
    }


def ensure_role(acct: str) -> str:
    iam = boto3.client("iam")
    trust = json.loads(json.dumps(TRUST))
    cond = trust["Statement"][0]["Condition"]
    cond["StringEquals"]["aws:SourceAccount"] = acct
    cond["ArnLike"]["aws:SourceArn"] = f"arn:aws:bedrock-agentcore:{C.REGION}:{acct}:*"

    created = False
    try:
        iam.get_role(RoleName=C.ROLE_NAME)
        iam.update_assume_role_policy(
            RoleName=C.ROLE_NAME, PolicyDocument=json.dumps(trust)
        )
        print(f"[deploy] role {C.ROLE_NAME} exists, trust policy refreshed")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=C.ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="AgentCore Runtime V1/V2 benchmark execution role",
        )
        created = True
        print(f"[deploy] created role {C.ROLE_NAME}")

    iam.put_role_policy(
        RoleName=C.ROLE_NAME,
        PolicyName="AgentCoreV2BenchExecutionPolicy",
        PolicyDocument=json.dumps(permissions_policy(acct)),
    )
    # IAM propagation: AgentCore validates the ECR URI against this policy at
    # create time and fails with "Access denied while validating ECR URI" if it
    # reads a stale version.
    time.sleep(20 if created else 10)
    return iam.get_role(RoleName=C.ROLE_NAME)["Role"]["Arn"]


def find_runtime(ctl, name: str):
    paginator = ctl.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt["agentRuntimeName"] == name:
                return rt
    return None


def wait_ready(ctl, runtime_id: str, timeout_s: int = 900) -> tuple[str, float]:
    t0 = time.perf_counter()
    while True:
        st = ctl.get_agent_runtime(agentRuntimeId=runtime_id)["status"]
        if st == "READY" or st.endswith("FAILED"):
            return st, time.perf_counter() - t0
        if time.perf_counter() - t0 > timeout_s:
            return f"TIMEOUT({st})", time.perf_counter() - t0
        time.sleep(3)


def main() -> int:
    acct = C.account_id()
    role_arn = ensure_role(acct)
    ctl = C.control_client()

    state = {}
    if C.STATE_FILE.exists():
        state = json.loads(C.STATE_FILE.read_text())

    for size in C.IMAGE_SIZES:
        for version in C.PLATFORM_VERSIONS:
            name = C.runtime_name(size, version)
            uri = C.image_uri(size, acct)
            common = dict(
                roleArn=role_arn,
                agentRuntimeArtifact={"containerConfiguration": {"containerUri": uri}},
                networkConfiguration={"networkMode": "PUBLIC"},
                protocolConfiguration={"serverProtocol": "HTTP"},
                lifecycleConfiguration={
                    "idleRuntimeSessionTimeout": C.IDLE_TIMEOUT_S,
                    "maxLifetime": C.MAX_LIFETIME_S,
                },
                environmentVariables={
                    "IMAGE_SIZE_LABEL": size,
                    "PLATFORM_VERSION_LABEL": version,
                },
                **C.platform_kwargs(version),
            )
            requested = common.get("platformVersion", "(omitted: service default)")

            existing = find_runtime(ctl, name)
            t_call = time.perf_counter()
            if existing:
                rid = existing["agentRuntimeId"]
                print(f"[deploy] updating {name} ({version}, {size})")
                ctl.update_agent_runtime(agentRuntimeId=rid, **common)
            else:
                print(f"[deploy] creating {name} ({version}, {size})")
                resp = ctl.create_agent_runtime(agentRuntimeName=name, **common)
                rid = resp["agentRuntimeId"]
            call_s = time.perf_counter() - t_call

            status, ready_s = wait_ready(ctl, rid)
            got = ctl.get_agent_runtime(agentRuntimeId=rid)
            arn = got["agentRuntimeArn"]
            actual_version = got.get("platformVersion", "?")
            print(
                f"[deploy]   {name}: {status} in {ready_s:.1f}s "
                f"(api call {call_s:.2f}s, platformVersion={actual_version})"
            )
            state[name] = {
                "size": size,
                "requested_version": version,
                "platform_version_field_sent": requested,
                "platform_version": actual_version,
                "runtime_id": rid,
                "arn": arn,
                "image_uri": uri,
                "status": status,
                "api_call_s": round(call_s, 3),
                "ready_s": round(ready_s, 2),
            }
            C.STATE_FILE.write_text(json.dumps(state, indent=2))

    print(f"[deploy] wrote {C.STATE_FILE}")
    bad = [k for k, v in state.items() if v["status"] != "READY"]
    if bad:
        print(f"[deploy] NOT READY: {bad}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
