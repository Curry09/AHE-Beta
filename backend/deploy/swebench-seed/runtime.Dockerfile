# syntax=docker/dockerfile:1
ARG SEED_IMAGE=auto-designer-seed:swebench-medium-hard-16
FROM ${SEED_IMAGE} AS seed
FROM ubuntu:22.04 AS py310
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.10 \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 supplies Python 3.12 for NexAU.  The historical scikit-learn
# workspace still needs the compatible Python 3.10 runtime copied from jammy.
FROM ubuntu:24.04
LABEL org.auto-designer.seed-runtime="1"

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/usr/local/bin:/usr/bin:/bin \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates coreutils git procps python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
COPY --from=py310 /usr/bin/python3.10 /usr/bin/python3.10
COPY --from=py310 /usr/lib/python3.10/ /usr/lib/python3.10/
COPY nexau-*.whl /tmp/
RUN python3 -m pip install --break-system-packages --no-cache-dir /tmp/nexau-*.whl \
    && rm /tmp/nexau-*.whl

COPY --from=seed /workspace/ /workspace/
COPY --from=seed /build-state.json /build-state.json
COPY prepare_swebench_runtime_tree.py /tmp/prepare_swebench_runtime_tree.py
RUN python3 /tmp/prepare_swebench_runtime_tree.py \
    && rm /tmp/prepare_swebench_runtime_tree.py

WORKDIR /workspace
CMD ["sh", "-lc", "trap 'exit 0' TERM INT; while :; do sleep 3600; done"]
