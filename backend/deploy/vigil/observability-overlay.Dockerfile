# Spec-0061: install the independently committed delivery runtime on a pinned base.
# No dependency or network change; use the full build for dependency upgrades.
ARG VIGIL_BASE_IMAGE
FROM ${VIGIL_BASE_IMAGE}
ARG OPENAGENTS_REVISION
COPY . /opt/openagents-src
RUN pip install --no-deps --no-build-isolation /opt/openagents-src \
    && python3 -c "from openagents.observations import evidence, gaps; assert 'developer' in evidence.ROLES"
LABEL org.opencontainers.image.openagents.revision=${OPENAGENTS_REVISION}
