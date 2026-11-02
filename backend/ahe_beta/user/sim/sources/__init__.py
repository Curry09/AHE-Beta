"""SeedSource 实现子包（spec-0009/T1）。

`seed_source._discover()` 在 import 期遍历本包逐一 import，触发各模块顶部 `@register`
的自注册。故新增一个供给源 = 在此落一个模块，无需改注册侧（spec-0009/T2 的 empty 源即此）。
"""
