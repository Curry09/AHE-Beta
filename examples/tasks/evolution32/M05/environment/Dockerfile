# Spec-0081/T5: retain the original base and supply its declared task interpreter.
ARG PYTHON_IMAGE=ghcr.io/mmjzmy/ahe-beta-tasks@sha256:aeb29bd7d63eb8220c87f768070bfdba8f5dee4d33c487fc2c3c545f9a0a7bde
ARG TASK_IMAGE=ghcr.io/mmjzmy/ahe-beta-tasks@sha256:e90095ce181e47a728407bbe4ecb39ebdeb54abb5aa598fc6efc7704d2570fd9
FROM ${PYTHON_IMAGE} AS task-python
FROM ${TASK_IMAGE}
COPY --from=task-python /opt/python/ /opt/python/
ENV PATH="/opt/python/bin:${PATH}"
COPY task-python.sh /etc/profile.d/50-task-python.sh
LABEL auto-designer.material="M05" org.opencontainers.image.title="M05 task environment" org.opencontainers.image.description="M05 task environment"
RUN bash -lc 'python -c "import sys,sqlite3; assert sys.version_info[:3] == (3,12,14); assert sqlite3.sqlite_version_info >= (3,35)" && python3 --version'
WORKDIR /workspace
CMD ["sleep", "infinity"]
