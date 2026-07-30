# Spec-0033/T1：vigil 交付面容器镜像——python + git + claude CLI + openagents 纯工具链。
# build context = 本地 OpenAgents checkout（pin 由 checkout 决定，与「uv tool 钉版本」同一纪律）；
# 构建入口用同目录 build.sh（校验 context 形状）。入口脚本不烘进镜像——由 run.py 在 docker run 时
# 只读挂载 entrypoint.sh（镜像保持通用工具链，脚本可迭代免重建）。
FROM python:3.12-bookworm

# claude CLI：native 安装器（无 node 依赖），装到 /root/.local/bin，软链进 PATH。
# 凭证不进镜像：运行时经 env 注入 ANTHROPIC_API_KEY 或 CLAUDE_CODE_OAUTH_TOKEN（见 run.py）。
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && claude --version

# openagents：从 build context（OpenAgents checkout）安装，console script 落 PATH。
COPY . /opt/openagents-src
RUN pip install --no-cache-dir /opt/openagents-src \
    && openagents --help >/dev/null

WORKDIR /work
