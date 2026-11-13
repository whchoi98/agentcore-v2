#!/usr/bin/env bash
# Delete everything this benchmark creates: the 8 agent runtimes, the ECR
# repository (and its images), and the execution role.
#
# Defaults to a dry run. Pass --yes to actually delete.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${SCRIPT_DIR}")"
PY="${ROOT}/.venv/bin/python"

REGION="$("${PY}" -c 'import sys;sys.path.insert(0,"'"${SCRIPT_DIR}"'");import config;print(config.REGION)')"
REPO="$("${PY}" -c 'import sys;sys.path.insert(0,"'"${SCRIPT_DIR}"'");import config;print(config.ECR_REPOSITORY)')"
ROLE="$("${PY}" -c 'import sys;sys.path.insert(0,"'"${SCRIPT_DIR}"'");import config;print(config.ROLE_NAME)')"
PREFIX="$("${PY}" -c 'import sys;sys.path.insert(0,"'"${SCRIPT_DIR}"'");import config;print(config.RUNTIME_PREFIX)')"

APPLY=false
[ "${1:-}" = "--yes" ] && APPLY=true
$APPLY || echo "=== DRY RUN (pass --yes to delete) ==="

echo "--- agent runtimes with prefix '${PREFIX}' in ${REGION}"
IDS="$(aws bedrock-agentcore-control list-agent-runtimes --region "${REGION}" \
  --query "agentRuntimes[?starts_with(agentRuntimeName,'${PREFIX}')].[agentRuntimeName,agentRuntimeId]" \
  --output text || true)"
if [ -n "${IDS}" ]; then
  echo "${IDS}"
  if $APPLY; then
    echo "${IDS}" | while read -r name id; do
      [ -z "${id}" ] && continue
      echo "deleting runtime ${name} (${id})"
      aws bedrock-agentcore-control delete-agent-runtime \
        --region "${REGION}" --agent-runtime-id "${id}" >/dev/null || true
    done
  fi
else
  echo "(none)"
fi

echo "--- ECR repository ${REPO}"
if aws ecr describe-repositories --repository-names "${REPO}" --region "${REGION}" >/dev/null 2>&1; then
  aws ecr describe-images --repository-name "${REPO}" --region "${REGION}" \
    --query 'imageDetails[].imageTags[0]' --output text || true
  if $APPLY; then
    echo "deleting repository ${REPO}"
    aws ecr delete-repository --repository-name "${REPO}" --region "${REGION}" --force >/dev/null
  fi
else
  echo "(absent)"
fi

echo "--- IAM role ${ROLE}"
if aws iam get-role --role-name "${ROLE}" >/dev/null 2>&1; then
  aws iam list-role-policies --role-name "${ROLE}" --query PolicyNames --output text
  if $APPLY; then
    for p in $(aws iam list-role-policies --role-name "${ROLE}" --query PolicyNames --output text); do
      aws iam delete-role-policy --role-name "${ROLE}" --policy-name "${p}"
    done
    aws iam delete-role --role-name "${ROLE}"
    echo "deleted role ${ROLE}"
  fi
else
  echo "(absent)"
fi

$APPLY && echo "=== done ===" || echo "=== nothing deleted ==="
