# Spec 0048 实现与历史校正说明

本变更修复的是用户模拟评估器的动作完整性，不改写任何冻结实验。历史数据应通过
`backend/scripts/audit_sim_action_integrity.py` 生成独立 correction artifact，并同时记录源码 pin 与模型 pin。

冻结证据基线：固定 16 题的 harness v0–v6 共 112 局，raw broad Accept 为 94，模型显式 broad Accept
为 53，非法 fallback 为 41；各轮非法数为 `5, 5, 5, 7, 9, 6, 4`。hard64 共 64 局，raw broad Accept
为 53，显式 broad Accept 为 26，非法 fallback 为 27。非法 evaluator 输出只降低有效样本分母，不归因为
harness fail。

2026-08-31 已用本审计脚本直接读取上述两组冻结 session：112 局与 hard64 的输出分别精确复现
`94/53/41` 和 `53/26/27`，未修改原始 JSON。

示例：

```bash
python backend/scripts/audit_sim_action_integrity.py SESSION_DIR \
  --output correction.json \
  --source-pin COMMIT_OR_IMAGE \
  --model-pin glm-5-2-fp8-wangyiding-mlcoding
```

认证入口为 `backend/scripts/e2e-spec-0048-final-check-convergence.sh`：离线 deterministic 测试始终运行；
明确配置 `USER_LLM_BASE_URL`、`USER_LLM_API_KEY`、`USER_LLM_MODEL` 时，会追加真实 final-check → re-judge →
re-intent → act canary。输出只保存模型与源码 pin，不保存密钥。

2026-08-31 真实 canary 已通过：源码 `fa8a7488f362bafcf7d01c2d5e898a7a5cc0b666`，模型
`glm-5-2-fp8-wangyiding-mlcoding`，每次调用上限 2048 tokens；结果为
`completed → satisfied → needs_final_check=false → accept`。
