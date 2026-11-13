# syntax=docker/dockerfile:1
#
# AgentCore Runtime agent image. Must be linux/arm64.
#
# PAD_MB grows the image with incompressible data so the same agent can be
# tested at several image sizes. /dev/urandom rather than /dev/zero because ECR
# stores layers gzip-compressed and zero padding would compress away, which
# would defeat the point of measuring pull/unpack cost at size.
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --no-compile -r requirements.txt \
 && pip uninstall -y pip \
 && rm -rf /usr/local/lib/python3.13/ensurepip /root/.cache

COPY agent.py ./

ARG PAD_MB=0
RUN if [ "${PAD_MB}" -gt 0 ]; then \
      dd if=/dev/urandom of=/app/.size-padding bs=1M count="${PAD_MB}" status=none; \
    fi

EXPOSE 8080
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
