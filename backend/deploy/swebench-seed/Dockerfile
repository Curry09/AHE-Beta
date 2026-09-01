FROM scratch

# Storage artifact only.  Do not use this image to execute sessions; derive the
# runnable image with runtime.Dockerfile (spec-0051).

COPY workspace/ /workspace/
COPY build-state.json /build-state.json
