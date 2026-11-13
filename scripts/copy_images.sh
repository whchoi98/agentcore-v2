#!/usr/bin/env bash
# Copy the benchmark images from one region's ECR to another, byte for byte.
#
# A new round in another region should run the exact image bits of the earlier
# round, so the only variable that changes is the region. `docker buildx
# imagetools create` copies the manifest and its blobs registry-to-registry
# without re-compressing layers, so the digests stay identical; the script
# checks that they do.
#
#   SRC_REGION=ap-northeast-1 BENCH_REGION=ap-northeast-2 ./scripts/copy_images.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${SCRIPT_DIR}")"
PY="${ROOT}/.venv/bin/python"

SRC_REGION="${SRC_REGION:-ap-northeast-1}"
DST_REGION="$("${PY}" -c 'import sys; sys.path.insert(0,"'"${SCRIPT_DIR}"'"); import config; print(config.REGION)')"
REPO="$("${PY}" -c 'import sys; sys.path.insert(0,"'"${SCRIPT_DIR}"'"); import config; print(config.ECR_REPOSITORY)')"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
TAGS=(200mb 1gb 2gb mem)

if [ "${SRC_REGION}" = "${DST_REGION}" ]; then
  echo "[copy] source and destination are both ${DST_REGION}; nothing to do" >&2
  exit 1
fi

SRC_REG="${ACCOUNT}.dkr.ecr.${SRC_REGION}.amazonaws.com"
DST_REG="${ACCOUNT}.dkr.ecr.${DST_REGION}.amazonaws.com"

if ! aws ecr describe-repositories --repository-names "${REPO}" --region "${DST_REGION}" >/dev/null 2>&1; then
  echo "[copy] creating ECR repository ${REPO} in ${DST_REGION}"
  aws ecr create-repository --repository-name "${REPO}" --region "${DST_REGION}" \
    --image-scanning-configuration scanOnPush=false >/dev/null
fi

for r in "${SRC_REGION}" "${DST_REGION}"; do
  aws ecr get-login-password --region "${r}" \
    | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${r}.amazonaws.com" >/dev/null
done

for tag in "${TAGS[@]}"; do
  echo "[copy] ${SRC_REG}/${REPO}:${tag} -> ${DST_REG}/${REPO}:${tag}"
  docker buildx imagetools create --tag "${DST_REG}/${REPO}:${tag}" "${SRC_REG}/${REPO}:${tag}"
  # imagetools wraps a single-platform manifest in a new manifest list, so the
  # tag would get a new digest even though the image inside is identical.
  # Point the tag at the original manifest instead (its blobs are now in the
  # destination repo), then drop the wrapper list.
  wrapper="$(aws ecr describe-images --region "${DST_REGION}" --repository-name "${REPO}" \
        --image-ids imageTag="${tag}" --query 'imageDetails[0].imageDigest' --output text)"
  manifest="$(aws ecr batch-get-image --region "${SRC_REGION}" --repository-name "${REPO}" \
        --image-ids imageTag="${tag}" --query 'images[0].imageManifest' --output text)"
  mtype="$(aws ecr batch-get-image --region "${SRC_REGION}" --repository-name "${REPO}" \
        --image-ids imageTag="${tag}" --query 'images[0].imageManifestMediaType' --output text)"
  # The repository is MUTABLE (create-repository default), so put-image moves
  # the tag; set -e stops the script if it does not.
  aws ecr put-image --region "${DST_REGION}" --repository-name "${REPO}" --image-tag "${tag}" \
    --image-manifest "${manifest}" --image-manifest-media-type "${mtype}" >/dev/null
  now="$(aws ecr describe-images --region "${DST_REGION}" --repository-name "${REPO}" \
        --image-ids imageTag="${tag}" --query 'imageDetails[0].imageDigest' --output text)"
  if [ "${now}" != "${wrapper}" ]; then
    aws ecr batch-delete-image --region "${DST_REGION}" --repository-name "${REPO}" \
      --image-ids imageDigest="${wrapper}" >/dev/null 2>&1 || true
  fi
done

echo "[copy] digest check"
fail=0
for tag in "${TAGS[@]}"; do
  s="$(aws ecr describe-images --region "${SRC_REGION}" --repository-name "${REPO}" \
        --image-ids imageTag="${tag}" --query 'imageDetails[0].imageDigest' --output text)"
  d="$(aws ecr describe-images --region "${DST_REGION}" --repository-name "${REPO}" \
        --image-ids imageTag="${tag}" --query 'imageDetails[0].imageDigest' --output text)"
  if [ "${s}" = "${d}" ]; then
    echo "  ${tag}: OK ${d}"
  else
    echo "  ${tag}: MISMATCH src=${s} dst=${d}"
    fail=1
  fi
done
exit "${fail}"
