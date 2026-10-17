# task-C5 交付说明

```
任务ID / 分支：task-C5 / docs/C5-touchstone-tau
交付文档：docs/design/C5-touchstone-tau.md（接口 / 数据格式 / 迁移步骤 / 工作量估算）
关键结论与推荐：
  - 方案 A 采用“离线 ref_ncs[R × n_pert] + 线上按药物读取参考分布 → tau_ref → reversal_index”。
  - R = 2000 条真实 Touchstone 参考查询 + 400 条随机基因集参考；top_n = 150（上/下调各 150）。
  - NCS 改为正负分别归一，按 (cell_id, pert_type) 分层，并给出 4 级回退链。
  - 药物级聚合改为细胞系内负 q33 / 正 q67，跨细胞系取最大绝对值（可配置回 max_abs）。
  - API 只加 tau_ref、reversal_index、ref_version 三个 Optional 字段；旧字段保留。
  - 前端主分数显示 tau_ref + 强弱标签（<= -90 强、<= -80 中），同时显示 0–1 逆转指数。
  - 功能上不依赖 L7a，但全量预计算性能强依赖：现有 12,328 行布局 32 核约 1–3 天；
    L7a 978 landmark + 秩缓存 16 核约 1–3 小时。基因空间必须参考集与线上查询一致。
D5 调查结果（服务器上有无 Touchstone 数据）：
  - 有。实际位于 keji@10.39.15.238:~/cmap/temp/touchstone_data/，约 14.9 GB（13.9 GiB）：
    touchstone_score.gctx（14,836,692,414 B）、293,619 条签名、21,577 个 pert_id、
    6,279 个 pert_iname、76 个细胞系；由 extract_touchstone.py 从 GSE92742 的
    is_touchstone=1 子集提取。
  - 但不在 app/config.py:28-30 期望的 ~/cmap/touchstone_data/（该目录不存在），
    现有代码读不到；需人工搬迁或配置 CMAP_TOUCHSTONE_DIR。
  - 现有 precompute_touchstone_ref.py 只生成 cell_reference.pkl / pert_reference.pkl
    等元数据统计，没有生成 ref_ncs，不能直接复用。
  - 推荐使用现有 GSE92742 版本（与 fast_matrix 同源、签名可对齐）；LINCS2020 作为后续
    独立 ref_version。
待人工确认（🧑‍⚖️）：是否立项实施、与 L7a 的排期关系
  - D5-a：确认参考集用 GSE92742（推荐）还是 LINCS2020。
  - D5-b：批准搬迁/软链 14.9 GB Touchstone 数据到可配置目录（生产目录保持只读）。
  - D5-c：确认 R=2000 + 400、top_n=150、MIN_REF=100。
  - D5-d：exclude_self 是否默认开启（推荐开启，避免自匹配泄漏）。
  - D5-e：聚合口径 cell_q33q67_v1（推荐）还是官方 max_abs_v1。
  - D5-f：强弱阈值按 tau_ref 的 -90/-80（对应 RI 0.90/0.80）确认。
  - D5-g：是否立项；建议 L7a 先行，C5 随后；若需提前上线可先出 full12328 过渡版本。
  - D5-h：旧 tau_score 保留一个版本周期并标 deprecated。
发现但未处理：
  - 服务器 Touchstone 数据与 config 默认路径不一致（未搬迁，遵守只读红线）。
  - 现有 precompute_touchstone_ref.py 的产物是元数据统计，不是方案 A 所需 ref_ncs。
  - touchstone_score.gctx 的矩阵方向与 dtype 尚未用 h5py 实测校验（文档中标注为实施前必做）。
  - 本任务未修改任何业务代码、未生成参考数据、未部署、未重启服务。
```

## 验收自检

| 任务要求 | 结果 |
|---|---|
| D5：服务器 Touchstone 数据调查 | 已实测回答：有数据，路径与配置不一致，详见文档 §2 |
| 预计算脚本输入/输出/格式/版本/并行/耗时 | 文档 §5，含 CLI、目录、meta.json、分片续跑、两种布局耗时表 |
| 三个函数的新算法 + 官方对应 | 文档 §3.3/§3.4/§3.5，含伪代码与回退/边界 |
| API 只加三字段 + 前端主分数与标签 | 文档 §8，含 schema、JSON 示例、兼容/降级、前端阈值 |
| 验证：跨细胞系自连接、C3 FDR 一致性 | 文档 §11.3/§11.4，含验收指标 |
| 迁移步骤可执行 | 文档 §10，7 个阶段含命令与验收 |
| 工作量估算 | 文档 §12，23–34 人日 + 机器时间 |
| Python 3.8 语法 | 文档中 3 个 Python 代码块已用 `ast.parse(feature_version=(3,8))` 校验通过 |
| 只出文档 | 本分支仅新增 `docs/design/C5-touchstone-tau.md` 与本交付说明 |
