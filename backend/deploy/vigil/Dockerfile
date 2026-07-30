# Spec-0033/T1：vigil 交付面容器镜像——python + git + claude CLI + openagents 纯工具链。
# build context = 本地 OpenAgents checkout（pin 由 checkout 决定，与「uv tool 钉版本」同一纪律）；
# 构建入口用同目录 build.sh（校验 context 形状）。入口脚本不烘进镜像——由 run.py 在 docker run 时
# 只读挂载 entrypoint.sh（镜像保持通用工具链，脚本可迭代免重建）。
FROM python:3.12-bookworm

# claude CLI：native 安装器（无 node 依赖）。凭证不进镜像：运行时经 env 注入（见 run.py）。
# 实证修复：容器必须以**非 root** 跑——claude 拒绝 root 下 bypassPermissions（而盒内必须 bypass，
# 否则 headless git 被权限门拒）。但 claude 装进非 root 家目录时构建会挂（安装器实测 flaky），
# 可靠做法：以 root 安装到 /root/.local → 放开读+执行权限（本镜像 /root 下无任何敏感物，凭证
# 全在运行时 env）→ 建非 root 用户 vigil 执行。
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && chmod 0755 /root && chmod -R a+rX /root/.local \
    && claude --version

# openagents：从 build context（OpenAgents checkout）安装，console script 落 PATH。
COPY . /opt/openagents-src
RUN pip install --no-cache-dir /opt/openagents-src \
    && openagents --help >/dev/null

# 非 root 运行用户（uid 固定 1000，方便挂载物权限对齐）；/work 为 clone 落点（entrypoint 使用）。
RUN useradd -m -u 1000 -s /bin/bash vigil && mkdir -p /work && chown vigil:vigil /work
USER vigil
WORKDIR /work

# 以 vigil 身份验证 claude 可执行（权限放开是否生效在构建期就暴露，不留到运行时）。
RUN claude --version
