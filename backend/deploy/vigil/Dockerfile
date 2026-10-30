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

# Spec-0033/T1：vigil 交付面容器镜像——python + git + claude CLI + OpenAgents + NexAU。
# 默认 build context = 本地 OpenAgents checkout；命名 context `nexau` = 本地 NexAU checkout。
# 两者的 pin 均由 checkout 决定，由 build.sh 统一校验和传入。
# 构建入口用同目录 build.sh（校验 context 形状）。入口脚本不烘进镜像——由 run.py 在 docker run 时
# 只读挂载 entrypoint.sh（镜像保持通用工具链，脚本可迭代免重建）。
FROM python:3.12-bookworm

ARG PIP_INDEX_URL
ARG CLAUDE_CODE_VERSION=2.1.261

# 本地 checkout 以非隔离模式构建，避免 pip 为每个项目反复创建并联网填充
# 临时构建环境。构建后端来自两个 pyproject.toml：OpenAgents=hatchling，
# NexAU=setuptools+wheel。
RUN pip install --no-cache-dir hatchling setuptools wheel

# claude CLI：native 安装器（无 node 依赖）。凭证不进镜像：运行时经 env 注入（见 run.py）。
# 实证修复：容器必须以**非 root** 跑——claude 拒绝 root 下 bypassPermissions（而盒内必须 bypass，
# 否则 headless git 被权限门拒）。但 claude 装进非 root 家目录时构建会挂（安装器实测 flaky），
# 可靠做法：以 root 安装到 /root/.local → 放开读+执行权限（本镜像 /root 下无任何敏感物，凭证
# 全在运行时 env）→ 建非 root 用户 vigil 执行。
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- "$CLAUDE_CODE_VERSION" \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && chmod 0755 /root && chmod -R a+rX /root/.local \
    && claude --version | grep -F "$CLAUDE_CODE_VERSION"

# openagents：从 build context（OpenAgents checkout）安装，console script 落 PATH。
COPY . /opt/openagents-src
RUN pip install --no-cache-dir --no-build-isolation /opt/openagents-src \
    && openagents --help >/dev/null

# harness v0 的运行时和技术契约均基于 NexAU。交付角色既要能运行 harness
# 测试，也要能审查当前 pin 的真实 API；因此不能只安装一个不可见的 wheel，保留
# checkout 于 /opt/nexau-src。运行容器为非 root，该目录不可写。
COPY --from=nexau . /opt/nexau-src
RUN pip install --no-cache-dir --no-build-isolation /opt/nexau-src "ag-ui-protocol==0.1.22" "anthropic<1" "greenlet>=3" \
    && python -c "from nexau import Agent, AgentConfig, Span, SpanType" \
    && chmod -R a-w /opt/nexau-src

# 交付面工程质量工具链：ruff + pytest。reviewer/implementer/deliver agent 的提示词把「ruff check
# 通过 + pytest 通过」列为自验/评审判据（OpenAgents 约定），在容器里实跑 `python -m ruff check .` /
# `python -m pytest -q`——缺工具则报 "No module named ruff/pytest" → 评审掷骰子（有时误判 REWORK、
# doc-only 的正确 PR 也被打回 → 卡到 needs-human，生产实证）。它们是交付面工具链、与 git/claude 同级，
# **必须 build 时烘进镜像**——egress 只放行 Anthropic API，运行时 pip 到不了 PyPI（见 deploy/gitea
# egress-proxy.conf）。NexAU 及其依赖同样必须在构建期完成，运行时不依赖 PyPI。
RUN pip install --no-cache-dir "ruff>=0.9.0" "pytest>=8.0.0" \
    && ruff --version && pytest --version

# 非 root 运行用户（uid 固定 1000，方便挂载物权限对齐）；/work 为 clone 落点（entrypoint 使用）。
RUN useradd -m -u 1000 -s /bin/bash vigil && mkdir -p /work && chown vigil:vigil /work
USER vigil
WORKDIR /work

# 以 vigil 身份验证 claude 可执行（权限放开是否生效在构建期就暴露，不留到运行时）。
RUN claude --version
