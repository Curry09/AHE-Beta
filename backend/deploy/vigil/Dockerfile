# Spec-0069/T3: public recipes build from frozen material directories. Explicit
# targets leave the historical build.sh/default final stage unchanged.
FROM python:3.12.13-bookworm AS unified-base
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates util-linux && rm -rf /var/lib/apt/lists/*
RUN curl -fLsS https://github.com/astral-sh/uv/releases/download/0.11.28/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/uv.tar.gz \
    && echo 'e490a6464492183c5d4534a5527fb4440f7f2bb2f228162ad7e4afe076dc0224  /tmp/uv.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/uv.tar.gz -C /tmp && cp /tmp/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv && rm -rf /tmp/uv*
COPY controller /opt/controller
WORKDIR /opt/controller
RUN uv sync --locked --python /usr/local/bin/python3 --extra experiments --extra dev
ENV PATH="/opt/controller/.venv/bin:$PATH" PYTHONPATH=/opt/controller/backend

FROM unified-base AS unified-vigil
COPY openagents /opt/openagents-src
WORKDIR /opt/openagents-src
RUN uv sync --locked --python /usr/local/bin/python3 --extra nexau --extra dev
RUN curl -fLsS https://downloads.claude.ai/claude-code-releases/2.1.284/linux-x64/claude -o /usr/local/bin/claude \
    && echo '5cd90aabd83f8a15136c35aa37bb1d92b348993573316643dc3fe4e04afbf88f  /usr/local/bin/claude' | sha256sum -c - \
    && chmod 0755 /usr/local/bin/claude && claude --version | grep -F '2.1.284'
ENV PATH="/opt/openagents-src/.venv/bin:$PATH" DISABLE_UPDATES=1 OPENAGENTS_NO_SELF_UPDATE=1
RUN useradd -m -u 1000 -s /bin/bash vigil && mkdir -p /work && chown vigil:vigil /work
USER vigil
WORKDIR /work
RUN openagents observation-capabilities --json && python -c 'from nexau import Agent'

FROM unified-base AS unified-seed
COPY task-source.tar.gz setup.sh requirements.lock task-build.json task-bootstrap.py /opt/task-build/
RUN python /opt/task-build/task-bootstrap.py && rm -rf /opt/task-build
LABEL org.auto-designer.seed-runtime="1"
WORKDIR /workspace

# Spec-0033/T1: vigil delivery surface container image — Python + Git + Claude CLI + OpenAgents + NexAU.
# Default build context = local OpenAgents checkout; named context `nexau` = local NexAU checkout.
# Pins for both are determined by checkout and uniformly validated and passed in by build.sh.
# Build entry point uses build.sh in the same directory (validates context shape). Entry script is not baked into the image — run.py
# read-only mounts entrypoint.sh at docker run time (image remains a generic toolchain; scripts can iterate without rebuild).
FROM python:3.12-bookworm

ARG PIP_INDEX_URL
ARG CLAUDE_CODE_VERSION=2.1.261

# Local checkout is built in non-isolated mode to avoid pip repeatedly creating and fetching temporary build environments over the network for each project.
# Build backends come from two pyproject.toml files: OpenAgents=hatchling,
# NexAU=setuptools+wheel。
RUN pip install --no-cache-dir hatchling setuptools wheel

# Claude CLI: native installer (no Node dependencies). Credentials do not go into the image; they are injected at runtime via environment variables (see run.py).
# Empirically validated fix: the container must run as a **non-root** user — Claude refuses bypassPermissions under root (yet the container must bypass it;
# otherwise headless git is rejected by permission gates). However, building with Claude installed into a non-root home directory hangs (the installer is flaky in practice).
# Reliable approach: install as root to /root/.local → grant read + execute permissions (this image has no sensitive data under /root; all credentials are
# in runtime environment variables) → create non-root user vigil to execute.
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- "$CLAUDE_CODE_VERSION" \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && chmod 0755 /root && chmod -R a+rX /root/.local \
    && claude --version | grep -F "$CLAUDE_CODE_VERSION"

# openagents: installed from build context (OpenAgents checkout), console script lands in PATH.
COPY . /opt/openagents-src
RUN pip install --no-cache-dir --no-build-isolation /opt/openagents-src \
    && openagents --help >/dev/null

# Harness v0's runtime and technical contract are both based on NexAU. The delivery role must both run harness
# tests and review the actual API of the current pin; therefore we cannot only install an invisible wheel but must preserve the
# checkout at /opt/nexau-src. The runtime container runs as non-root; this directory is not writable.
COPY --from=nexau . /opt/nexau-src
RUN pip install --no-cache-dir --no-build-isolation /opt/nexau-src "ag-ui-protocol==0.1.22" "anthropic<1" "greenlet>=3" \
    && python -c "from nexau import Agent, AgentConfig, Span, SpanType" \
    && chmod -R a-w /opt/nexau-src

# Delivery surface engineering quality toolchain: ruff + pytest. The prompts for reviewer/implementer/deliver agents list "ruff check
# passes + pytest passes" as self-validation/review criteria (OpenAgents convention); run `python -m ruff check .` /
# `python -m pytest -q`——if tools are missing, report "No module named ruff/pytest" → review dice roll (sometimes false positives for REWORK,
# doc-only PRs also get rejected → stuck in needs-human, production evidence). They are delivery-layer toolchain, at the same level as git/claude,
# **must be baked into the image at build time**——egress only permits Anthropic API, at runtime pip cannot reach PyPI (see deploy/gitea
# egress-proxy.conf). NexAU and its dependencies must also be completed during build; no PyPI dependency at runtime.
RUN pip install --no-cache-dir "ruff>=0.9.0" "pytest>=8.0.0" \
    && ruff --version && pytest --version

# run as non-root user (uid fixed at 1000 for convenient mount permission alignment); /work is the clone destination (used by entrypoint).
RUN useradd -m -u 1000 -s /bin/bash vigil && mkdir -p /work && chown vigil:vigil /work
USER vigil
WORKDIR /work

# authenticate claude as executable via vigil identity (permission grants are exposed at build time, not deferred to runtime).
RUN claude --version
