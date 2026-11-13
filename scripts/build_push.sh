#!/usr/bin/env bash
# Build the agent image at each size and push to ECR (ap-northeast-1).
# Host is aarch64, so linux/arm64 builds natively with no QEMU.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${SCRIPT_DIR}")"
PY="${ROOT}/.venv/bin/python"

REGION="$("${PY}" -c 'import sys; sys.path.insert(0,"'"${SCRIPT_DIR}"'"); import config; print(config.REGION)')"
REPO="$("${PY}" -c 'import sys; sys.path.insert(0,"'"${SCRIPT_DIR}"'"); import config; print(config.ECR_REPOSITORY)')"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

# size:pad_mb — keep in sync with config.IMAGE_SIZES
SIZES=("200mb:0" "1gb:797" "2gb:1821")

if ! aws ecr describe-repositories --repository-names "${REPO}" --region "${REGION}" >/dev/null 2>&1; then
  echo "[build] creating ECR repository ${REPO}"
  aws ecr create-repository --repository-name "${REPO}" --region "${REGION}" \
    --image-scanning-configuration scanOnPush=false >/dev/null
fi

echo "[build] docker login ${REGISTRY}"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

for entry in "${SIZES[@]}"; do
  size="${entry%%:*}"
  pad="${entry##*:}"
  uri="${REGISTRY}/${REPO}:${size}"
  echo "[build] ${size} (PAD_MB=${pad}) -> ${uri}"
  docker build --platform linux/arm64 --build-arg "PAD_MB=${pad}" \
    -t "${uri}" "${ROOT}/agent"
  docker push "${uri}"
  # Free local disk between sizes; the padded images are large.
  docker image rm "${uri}" >/dev/null 2>&1 || true
done

echo "[build] sizes as reported by ECR:"
aws ecr describe-images --repository-name "${REPO}" --region "${REGION}" \
  --query 'sort_by(imageDetails,&imagePushedAt)[].{tag:imageTags[0],MB:imageSizeInBytes}' \
  --output table
