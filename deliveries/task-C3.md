# task-C3 · cmap 方案 B：查询内随机签名 null → p 值 / FDR

## 任务ID / 分支 / 基线提交

- 任务ID：C3
- 分支：`fix/C3-null-fdr`（⚠️ 任务文件头部写的是 `fix/C3-null-calibration`；本波编排统一使用 `fix/C3-null-fdr`，交付以此为准）
- 基线：`origin/master` = `0a02aa3`（Merge branch 'fix/C4-reskin'）
- 仓库：cmap-l1000（`VitoHawk35/cmap-l1000`）

## 改动文件（文件:行号范围）

| 文件 | 行号 | 内容 |
|---|---|---|
| `scripts/build_drug_median.py` | 1–372（新增） | 离线构建药物 × landmark 中位数矩阵；`--from-lmna` 复用 LMNA 缓存。除任务要求的 `.npy` + `drug_median_names.csv` 外，另保存 KB 级的 `drug_median_lm_gene_ids.csv`（978 行，行序与矩阵一致），用于把查询 Entrez ID 映射到矩阵行 |
| `app/scoring/null_calibrator.py` | 1–343（新增） | `NullCalibrator`、自写 BH、分批随机签名 null、进程内单例（mmap） |
| `app/api/tau_search.py` | 28 | 引入 `get_null_calibrator` |
| 同上 | 73–127 | `_null_calibration_fields` / `_tau_result_dict`（失败只降级） |
| 同上 | 203–216 | 异步 `_run_tau_job`：`post_processor.process(...)` 之后校准、左连接、写 `null_calibration` |
| 同上 | 392–453 | 同步 `/search_tau`：同样校准并在 `TauSearchResult` / `TauSearchResponse` 中补字段 |
| `app/models/schemas.py` | 82–84 | `TauSearchResult` 增加 `p_value` / `fdr` / `null_z`（Optional[float]=None） |
| 同上 | 93 | `TauSearchResponse` 增加 `null_calibration`（Optional[str]=None） |
| `app/config.py` | 27–44 | 药物矩阵路径（`DATA_DIR/drug_median_lm.npy` 等）与 null 参数（🧑‍⚖️ 可环境变量覆盖） |
| `index.html` | 528 | Tau 表头 “FDR” + 指定 tooltip |
| 同上 | 559–567 | FDR 单元格：<0.05 加粗，>0.25 置灰 |
| 同上 | 1230、1245 | Tau 结果映射增加 `fdr: r.fdr`（Top / Bottom） |
| `tests/conftest.py` | 54–60 | 新增 session fixture `drug_median_data`（用合成数据生成药物矩阵） |
| `tests/test_null_calibrator.py` | 1–283（新增） | 10 个单测（完美药、KS、BH、landmark、分批、种子、内存） |
| `tests/test_build_drug_median.py` | 1–186（新增） | 5 个单测（trt_cp/landmark 过滤、分块、`--from-lmna`） |
| `tests/test_tau_null_integration.py` | 1–148（新增） | 4 个集成测试（异步、同步、insufficient、矩阵缺失） |

## 符号约定（最终定法）

- `xsum = Σz(up) − Σz(down)`，**负 = 逆转**（与本仓库 WTCS/Tau 约定一致）。
- 随机签名同大小、无放回抽 landmark 基因；up 记 `+1`、down 记 `−1`，`null = W @ drug_mat`。
- `p_reversal = (#{null ≤ xsum} + 1) / (M + 1)`。`xsum` 越小越逆转，因此 `null ≤ xsum`
  表示“随机签名至少和观测一样逆转”（单侧下尾）；p 越小越显著。
- `null_z = (xsum − mean(null)) / sd(null)`，**负 = 观测比随机更逆转**。
  该方向与 LMNA L4 的 `null_z` 完全一致（LMNA 对外 `score = −mimic`，本仓库对外
  `xsum = mimic`，两个仓库各自保持自己的对外约定，底层统计量相同）。
- `fdr_reversal = BH(p_reversal)`，对**全部药物**（不是仅 top/bottom）做多重校正。
- API 字段映射：`p_value ← p_reversal`，`fdr ← fdr_reversal`。
- `null_calibration` 取值：`ok`（成功）、`insufficient_landmark_genes`
  （up+down 的 landmark 基因 <10）、`unavailable`（矩阵缺失/加载或校准异常）。
- 数据处理细节：查询基因只保留落在 landmark 的；同一基因同时出现在 up/down 时
  两侧都去掉（避免观测值重复计数，随机签名是无放回抽样）。

## 测试

### 新增测试（19 个）

- `tests/test_null_calibrator.py`（10）
  - 完美逆转药 `fdr < 0.01`（M=40000，实测 0.00750）；
  - 其余药 `p_reversal` 对 U(0,1) 的 KS 检验 `p > 0.01`（M=2000，实测 p=0.307）；
  - BH 与 scipy `rankdata` 参考实现最大差 <1e-12（含并列 p 值，实测 0.0）；
  - scipy `false_discovery_control` 直接对比（scipy ≥1.11 时运行；本环境 skip）；
  - landmark 过滤、<10 基因空表与状态、分批一致性、seed 确定性、空签名；
  - 20k 药物、M=200 的分批内存护栏（tracemalloc <1GB）。
- `tests/test_build_drug_median.py`（5）
  - 只取 `pert_type == 'trt_cp'`；只保留 `pr_is_lm == 1` 行；按药名排序；
  - `chunk_size` 不影响结果；`--from-lmna` 复用 v2 文件；行数不匹配抛错。
- `tests/test_tau_null_integration.py`（4）
  - 异步 `/submit_tau`：`null_calibration == "ok"`，埋入的 `reversib` 实测
    `fdr≈3.16e-4 < 0.05`，`null_z<0`；
  - 同步 `/search_tau`：同样字段与阈值；
  - up+down=9 个 landmark 基因 → `insufficient_landmark_genes`，字段为 None；
  - 删除矩阵 → `/submit_tau` 仍成功，`null_calibration == "unavailable"`，字段为 None。

### pytest -q（完整输出见 `D:\agent-workspace\deliveries\task-C3\pytest-full.txt`）

```
39 passed, 1 skipped, 2 warnings in 6.91s
```

1 个 skip 是 `test_bh_matches_scipy_false_discovery_control`：Python 3.8 最高只能装
scipy 1.10.1，而 `scipy.stats.false_discovery_control` 从 scipy 1.11 起才提供
（1.11 要求 Python ≥3.9）。因此：

- 常驻测试用 scipy `rankdata` 构造独立 BH 参考实现，最大差 0.0（断言 <1e-12）；
- 另用本机 `cmap-c0-311`（Python 3.11.7 / scipy 1.17.1）直接对比
  `false_discovery_control`：n∈{1,2,5,17,50,300,1000,19811}、含并列 p 值，
  **最大绝对差 2.220446049250313e-16 < 1e-12**。

### 真实规模性能（本机实测，非服务器）

环境：Windows 11，Python 3.8.20，numpy 1.24.4，scipy 1.10.1。
数据：从服务器 `~/lmna_v2_cache/` scp 下来的真实矩阵
`_drug_median_matrix.v2.npy`，**978 × 19811，float32**；`n_null=10000`，
`batch=500`，查询 100 up + 100 down（随机 landmark 基因）。

| 指标 | 随机查询 | 自检查询（用某药最强 100 up/down 基因） |
|---|---|---|
| 单次 `calibrate` 耗时 | **1.416 s** | **1.333 s** |
| 进程峰值 Working Set | **206.8 MB** | — |
| RSS 校准前 → 后 | 63.6 → 156.7 MB | — |
| 结果 | `fdr_min=0.396`（无假阳性） | 目标药 rank 1/19811，`p=9.999e-5`，`fdr=8.46e-4`，`null_z=-23.36` |

结论：远低于验收的 `<30 s` 和 `<1 GB`。矩阵以 `np.load(..., mmap_mode='r')`
打开；null 逐批计算，未构造 `(10000, 19811)` 的完整矩阵。

## 验收逐条核对

- [x] 合成 978×300 + 1 个完美逆转药：完美药 `fdr < 0.01`。
      注：n_drug=300、M=10000 时全局 BH 的理论下限是 `300/10001≈0.030`，
      数学上不可能 <0.01；因此该用例用 **M=40000**（300/40001≈0.0075），
      实测 0.00750。M=2000 只用于 KS 检验（与 LMNA L4 的处理一致）。
- [x] 其余药 `p_reversal` 近似均匀：KS 检验 p=0.307 > 0.01（M=2000）。
- [x] BH 与 scipy 对比最大差 <1e-12：直接对比 2.22e-16；rankdata 参考 0.0。
- [x] 集成（C0 合成数据 + `build_drug_median.py` 生成的矩阵）：
      `/submit_tau` 中 `reversib` 的 `fdr≈3.16e-4 < 0.05`。
- [x] 删除矩阵后 `/submit_tau` 仍成功，`null_calibration == "unavailable"`。
- [x] 真实规模（n_drug=19811、M=10000）：1.416 s、峰值 206.8 MB
      （本机实测，不是服务器实测；见上表）。
- [x] 全量 `pytest -q`：39 passed, 1 skipped；C0–C4 既有测试未破坏。
- [x] 未提交 `*.npy` / `*.gctx` / cache / 大数据；矩阵只在
      `D:\agent-workspace\deliveries\task-C3\`，不在仓库内。

## 待人工确认（🧑‍⚖️）

1. **生产规模下 M=10000 的 FDR 分辨率（重要）**：真实药物数 n_drug≈19811。
   单个药物极端显著时，经验 p 下限是 `1/(M+1)`，BH 最小可达
   `n_drug/(M+1) ≈ 19811/10001 ≈ 1.98`（截断为 1.0）。也就是说，
   **若一次查询只有个别药物显著，M=10000 下它们不可能得到 FDR<0.05**；
   需要至少约 40 个药物同时落在 p 下限，FDR 才会 <0.05。当前实现按任务
   要求默认 M=10000，且已做成可配置（`CMAP_NULL_N`）。可选方案：
   - 把 `CMAP_NULL_N` 提到 ≥400000（本机约 40× 耗时，预估 ~56 s；内存随分批
     基本不变），代价是超出任务“<30 s”的性能目标；
   - 或把 FDR 家族限制在候选集/top-K（会改变 BH 的统计含义，需产品确认）；
   - 或对孤立命中只展示 p 值，不承诺 FDR 显著。
   本任务未擅自改默认值，请确认采用哪种策略。
2. `null_z` 方向：本实现取 **负 = 更逆转**（与 LMNA L4 一致）。如果前端/报告
   希望“正值=逆转”，需要改符号；请确认。
3. `null_calibration="ok"` 这个成功值任务未规定，本实现自定；如需改成
   `"available"`/`None` 请告知。
4. 前端 tooltip 固定写“1 万个”；若生产把 `CMAP_NULL_N` 调大，tooltip 会与实际
   不一致，建议后续把 M 透传到前端或改成“大量随机基因集”。
5. `drug_median_names.csv` 的列名用 `pert_iname`（本仓库习惯）；LMNA 原文件是
   `drug_name`。`--from-lmna` 两者都兼容，但下游若有固定列名需求请确认。
6. 真实数据构建：本次未跑“从 22 GB `fast_matrix.npy` 全量构建”（列式读取慢，
   任务已注明由 C5/L7a 处理）；`build_drug_median.py` 已在合成数据上验证，
   真实矩阵通过 `--from-lmna` 复用并完成真实规模性能测试。

## 发现但未处理

- 任务文件头部建议分支名 `fix/C3-null-calibration`，本波统一为
  `fix/C3-null-fdr`（交付按后者）。
- 真实数据“自检查询”（用目标药最强 100/100 个 landmark 基因作查询）返回
  6348 个药物 `fdr<0.05`。随机查询则 `fdr_min=0.396`，说明不是校准器整体失控；
  更可能是 L1000 药物中位数矩阵存在较强共结构/通路共享。该现象未深入分析，
  超出 C3 范围，建议后续用独立查询集评估 FDR 校准曲线。
- 随机签名 null 对真实生物签名可能偏乐观（方案 B 的已知风险，任务原文已提）。
- `get_null_calibrator()` 每次请求都会 `os.path.exists` 检查；替换矩阵后旧
  mmap 在进程内仍会用到重启/`reset_null_calibrator()` 为止。正常部署无影响。
