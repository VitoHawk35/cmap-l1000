# C5 方案 A 设计文档：Touchstone 参考集 + CLUE 标准 tau

> 任务：task-C5（P2，只出方案，不实施）
> 仓库：cmap-l1000（基线 `origin/master`，aa79530）
> 分支：`docs/C5-touchstone-tau`
> 文档状态：设计提案，等待人工确认（D5 及相关参数）后才实施
> 编写日期：2026-10-17
> 范围：本文件只描述接口、数据格式、算法、迁移步骤、验证方案与工作量。本任务不修改任何业务代码、不生成参考数据、不部署、不重启服务。

---

## 0. 结论摘要

1. **D5 已有答案：服务器上存在 Touchstone 参考数据。** 数据位于 `keji@10.39.15.238:~/cmap/temp/touchstone_data/`，由 `extract_touchstone.py` 从 GSE92742 的 `is_touchstone=1` 子集提取，约 14.9 GB（约 13.9 GiB），包含 293,619 条 Touchstone 签名、21,577 个 `pert_id`、6,279 个 `pert_iname`、76 个细胞系。**但数据不在 `app/config.py:28-30` 期望的 `~/cmap/touchstone_data/`（该目录不存在）**，所以现有代码即使接线也读不到；需要人工搬迁或以环境变量指向实际目录（本任务未做）。
2. **推荐参考集使用现有 GSE92742 版本**，不用 LINCS2020。理由：它与业务库 `fast_matrix.npy` 同源、签名 ID 可直接对齐、无需再下载百 GB 级数据；tau 的可比性要求参考查询和线上查询使用同一评分空间与同一库版本。LINCS2020 留作后续独立 `ref_version`。
3. **方案 A 的落地形态**：离线预计算 `ref_ncs[R × n_pert]`（R=2000 条真实 Touchstone 参考查询 + 400 条随机签名查询），线上对返回的每个药物读取该药物的参考 NCS 分布，计算 `tau_ref` 与 `reversal_index`，API 只加字段、不改旧字段。
4. **L7a 是性能前提，不是功能前提。** 功能上可以用现有 12,328 × 473,647 的按行 memmap 完成，但全量预计算在 32 核上约 **1–3 天**（与报告估计一致）；采用 L7a 的 978 landmark、按签名存储 memmap 后可降到 **约 1–3 小时**（16 核，含 I/O）。此外，特征空间必须与线上查询一致：若参考集使用 978 landmark，线上 WTCS 也必须切到 978 landmark；否则 `ref_version` 不可比。
5. **排序与展示会变化**：`top_results`/`bottom_results` 改为按 `tau_ref` 排序，前端主分数显示 `tau_ref` + 强弱标签（`<= -90` 强、`<= -80` 中），同时显示 `reversal_index`（0–1）。旧 `tau_score` 保留但标记 deprecated。

---

## 1. 现状与问题（行号已核实）

| 位置 | 现状 | 问题 |
|---|---|---|
| `app/core/post_processor.py:271-327` `_calculate_tau` | 取同一次查询结果里的 Touchstone 药物 `summary_ncs`，按正负分别算百分位 | 这是**查询内相对排名**，百分位天然均匀，跨查询不可比；Touchstone 药物少于 10 个时退化为 `z × 50`（:282-290） |
| `app/core/post_processor.py:180-217` `_calculate_ncs` | 每个 `cell_id` 内取 Touchstone 的 `max(abs(pos_mean), abs(neg_mean))` 作为统一分母 | 正负未分别归一；未按 `pert_type` 分层；Touchstone 少于 10 条时整段跳过归一化 |
| `app/core/post_processor.py:219-268` `_aggregate_by_perturbagen` | 每个 `pert_iname` 跨所有实例取绝对值最大的 NCS | 实例越多越容易取到极端值（多重比较偏倚）；溯源只能说明“极值来自哪次实验” |
| `app/config.py:28-30` | 定义了 `TOUCHSTONE_DIR`、`TOUCHSTONE_GCTX_PATH`、`TOUCHSTONE_SIGINFO_PATH` | 全仓库无任何代码读取这三个常量；且默认路径 `PROJECT_ROOT/touchstone_data` 在服务器上不存在 |
| `app/api/tau_search.py:145-175` | 把 `post_processor` 结果逐字段转 dict | 新增字段需要在两处（top/bottom）同步补充 |
| `app/models/schemas.py:68-80` `TauSearchResult` | 9 个字段，无绝对尺度字段 | 需要新增 `tau_ref`、`reversal_index`、`ref_version`，只加不改 |
| `index.html:505-537`、`1133-1165` | 表格“得分”列映射 `tau_score`，WTCS 列映射 `best_wtcs` | 主分数需要改为 `tau_ref`/逆转指数，并增加强弱标签 |

补充事实（实测）：

- 全库 `sig_info` 共 473,647 条签名，`pert_iname` 去重 28,927 个（含对照与各类扰动）；这是 `ref_ncs` 列数的上界。
- Touchstone 文件中按 `pert_type` 计：`trt_cp` 73,509 条、`trt_sh` 147,888 条、`trt_sh.cgs` 35,747 条、`trt_oe` 19,767 条、`ctl_vehicle` 14,368 条、`ctl_vector` 2,340 条。
- 现有 `precompute_touchstone_ref.py` **只生成元数据统计**（`cell_reference.pkl`、`pert_reference.pkl`、`touchstone_pert_summary.txt`），**没有生成 `ref_ncs` 矩阵**，不能直接复用为方案 A 的参考分布。

---

## 2. D5 调查结果（服务器只读实测）

### 2.1 使用的命令

```bash
ssh -i ~/.ssh/lmna_deploy keji@10.39.15.238 \
  "ls -la ~/cmap/cmap_data; find ~/cmap -maxdepth 3 -iname '*touchstone*'"

ssh -i ~/.ssh/lmna_deploy keji@10.39.15.238 \
  "ls -la ~/cmap/temp/touchstone_data; \
   wc -l ~/cmap/temp/touchstone_data/touchstone_pert_ids.txt \
         ~/cmap/temp/touchstone_data/touchstone_sig_ids.txt; \
   head -3 ~/cmap/temp/touchstone_data/touchstone_siginfo.txt"
```

只读操作：仅 `ls`、`find`、`wc`、`head`、`gzip -dc | awk`，未写服务器、未安装依赖、未重启服务。

### 2.2 实测结果

`~/cmap/cmap_data/`（64 GB）：

| 文件 | 大小 | 说明 |
|---|---:|---|
| `fast_matrix.npy` | 23,356,480,864 B (21.8 GiB) | 业务库，12,328 × 473,647 float32，按基因行存储 |
| `col_sig_ids.csv` | 17,907,075 B | 473,647 个签名 ID，矩阵列顺序 |
| `row_gene_ids.csv` | 79,847 B | 12,328 个基因 ID，矩阵行顺序 |
| `GSE92742_Broad_LINCS_Level5_COMPZ.MODZ_n473647x12328.gctx(.gz)` | 23.4 GB / 21.3 GB | 原始 GSE92742 Level 5 |
| `GSE92742_Broad_LINCS_{sig,pert,gene,cell}_info.*` | 0.5–11 MB | 原始元数据 |
| `21dct_degs.csv`、`col_sig_ids.csv`、`测试数据.xlsx` 等 | — | 其他业务数据 |

**`~/cmap/cmap_data/` 内没有 Touchstone 文件。**

`~/cmap/temp/touchstone_data/`（14.9 GB（约 13.9 GiB），2026-04-09 生成）：

| 文件 | 大小 | 说明 |
|---|---:|---|
| `touchstone_score.gctx` | 14,836,692,414 B（约 14.84 GB / 13.82 GiB） | Touchstone 表达矩阵，HDF5/GCTX；与 293,619 × 12,328 float32 的理论大小 14.48 GB 基本一致（差额为 GCTX 元数据/索引），实施前需用 `h5py` 校验维度与方向 |
| `touchstone_sig_ids.txt` | 10,682,390 B | 293,619 条签名 ID |
| `touchstone_siginfo.txt` | 63,898,307 B | 签名元数据（sig_id、pert_id、pert_iname、pert_type、cell_id、dose、time 等） |
| `touchstone_pert_ids.txt` | 341,420 B | 21,577 个 Touchstone `pert_id` |
| `touchstone_pert_summary.txt` | 227,979 B | 6,279 个 `pert_iname` 的细胞系数/类型汇总 |
| `cell_reference.pkl` | 1,971 B | 现有脚本生成的细胞系计数，**不是 NCS 参考分布** |
| `pert_reference.pkl` | 267,232 B | 现有脚本生成的药物计数，**不是 NCS 参考分布** |

Touchstone 数据统计：

- 唯一 `pert_id`：21,577
- 唯一 `pert_iname`：6,279（`trt_cp` 2,429、`trt_sh.cgs` 3,799、`trt_oe` 49、对照 2）
- 签名数：293,619
- 细胞系数：76；签名最多的细胞系为 MCF7 (40,252)、PC3 (37,960)、VCAP (29,643)、A549 (28,387)、A375 (26,264)、HA1E (25,913)、HT29 (24,241)、HCC515 (22,523)、HEPG2 (21,617)、NPC (6,513)
- 每个药物覆盖的细胞系数：最小 4、中位数 9、最大 70、均值 11.9

### 2.3 D5 结论

**有数据，且足够支撑方案 A。** 但有两个必须由人处理的运维事实：

1. **路径不一致**：`app/config.py:28-30` 期望 `~/cmap/touchstone_data/`，实际在 `~/cmap/temp/touchstone_data/`。实施时需二选一：把目录搬到项目根下（或建软链），或新增 `CMAP_TOUCHSTONE_DIR` 环境变量并在 `config.py` 读取。生产目录只读红线意味着这一步由人工在部署窗口执行，agent 不做。
2. **数据版本**：现有文件由 `extract_touchstone.py` 从 **GSE92742** 提取。推荐直接采用；如果改为 LINCS2020，需要重新下载/提取，并作为新的 `ref_version`，不能与 92742 参考分布混用。

**推荐：`ref_version` 采用 GSE92742 Touchstone（现有数据），LINCS2020 作为后续可选升级。**

---

## 3. 与 CLUE 官方定义的对应关系

### 3.1 术语

| 本方案 | 官方/文献 | 说明 |
|---|---|---|
| `wtcs` | Weighted Connectivity Score / KS 富集分 | 不变，沿用 `app/scoring/wtcs_scorer.py` |
| `ncs` | Normalized Connectivity Score | 正负分别归一，按“细胞系 × 扰动类型”分层 |
| `summary_ncs` | Perturbagen summary NCS | 药物级聚合结果 |
| `ref_ncs[R, p]` | Reference NCS distribution | 参考查询 `r` 对药物 `p` 的 NCS |
| `tau_ref` | Tau (CMap) | `-100..100`，负=逆转，正=相似/加重 |
| `reversal_index` | 本系统新增 | `max(0, -tau_ref) / 100`，`0..1` |

统一符号约定（与任务文件一致）：**Tau 负 = 逆转，正 = 相似/加重；逆转指数越大越逆转。**

### 3.2 WTCS（不变）

沿用现有实现：对每个候选签名，把 12,328（或 L7a 的 978 landmark）个基因按表达量降序排列；分别计算上调、下调基因的 KS 型富集分 `ES_up`、`ES_down`；仅当二者符号相反时 `WTCS = (ES_up - ES_down) / 2`，否则为 0。本方案不改 WTCS。

### 3.3 NCS：正负分别归一 + 分层

对一次查询的结果表 `df`（每条签名一行，含 `cell_id`、`pert_type`、`is_touchstone`、`score=WTCS`）：

1. 取 `is_touchstone == 1` 且 `pert_type in {trt_cp, trt_sh, trt_sh.cgs}` 的行作为归一化参考（`trt_oe` 是否纳入作为配置项 `NCS_INCLUDE_OE`，默认 0）。
2. 对每个分层 `stratum = (cell_id, pert_type)`：
   - `pos_ref = {score : score > 0}`，`neg_ref = {score : score < 0}`
   - `pos_denom = mean(pos_ref)`，`neg_denom = abs(mean(neg_ref))`
3. 对分层内每条签名（包括 Touchstone 自身）：
   - `score >= 0` 时 `ncs = score / pos_denom`
   - `score < 0` 时 `ncs = -(|score| / neg_denom)`，即 `ncs = score / neg_denom`
4. 分层样本不足时的回退层级（依次尝试，任一满足即停）：
   1. `(cell_id, pert_type)`，要求正负各有至少 `MIN_REF_PER_SIGN = 5` 条、总数至少 10 条；
   2. `pert_type`；
   3. `cell_id`（合并所有 `pert_type`）；
   4. 全局 Touchstone；
   5. 仍不足：`ncs = score`（恒等映射），并置 `ncs_fallback = 1` 供诊断。
5. 分母保护：若 `denom < 1e-3`，按回退层级继续；最终仍无效时 `denom = 1e-3`。正、负分母**独立回退**：若只有一侧样本不足，只对该侧使用下一层级，另一侧保持当前层。
6. 不截断 NCS。非有限值（NaN/Inf）置 0 并计数上报。

与官方的对应：官方 NCS 正是“正、负分数分别除以同细胞系（并按扰动类型分层）Touchstone 的正/负均值”；本方案把现有单分母改为双分母并补齐分层与回退链。

### 3.4 药物级聚合：细胞系内分位数 + 跨细胞系取最大绝对分位

对每个 `pert_iname`：

1. 按 `cell_id` 分组；
2. 细胞系内正负分开：
   - 负分支：取 `quantile(ncs[ncs < 0], 0.33)`（方向上更极端，等价于 `|NCS|` 的 67 分位）
   - 正分支：取 `quantile(ncs[ncs > 0], 0.67)`
3. 在所有细胞系的所有候选值中，取绝对值最大的一个作为 `summary_ncs`；
4. 溯源：在该细胞系内找到与所选分位值最接近的真实实例，记录 `best_wtcs`、`best_cell_id`、`best_dose`；若该细胞系只有 1 条实例，则直接使用该实例；
5. `cell_count` 保持为该药物出现过的不同细胞系数。

与官方的对应：官方 perturbagen summary 也是在实例间取“最强连接”；本方案用 **细胞系内 q33/q67 再跨细胞系取最大** 替代“全实例直接取极值”，目的是降低“实例数越多越容易极端”的偏倚，同时仍保留方向性。该选择作为配置 `AGG_MODE=cell_q33q67_v1`，并保留 `max_abs_v1`（旧逻辑）用于 A/B。

边界：

- 某细胞系只有正分或只有负分：只使用存在的一侧；
- `pert_iname` 为空或 `NaN`：不参与聚合，不进入 `ref_ncs` 列；
- 同一 `pert_iname` 同时存在多种 `pert_type`：与现状一致，只按名称聚合，`pert_type` 记为出现次数最多的类型，另存 `pert_types` 逗号分隔值；
- 浮点并列：取索引最小者，保证确定性。

### 3.5 tau_ref 与逆转指数

对药物 `p`，设 `r = ref_ncs[:, p]`（仅 `kind=touchstone` 的参考行、有限值），查询药物级 NCS 为 `q`：

```text
n_eff = count(finite(r))
if exclude_self: 去掉来源 perturbagen == p 的参考行后再计算 n_eff
if n_eff < MIN_REF (默认 100):
    tau_ref = null
else:
    lt  = count(|r_i| <  |q|)
    eq  = count(|r_i| == |q|)
    pct = (lt + 0.5 * eq) / n_eff          # 0..1
    tau_ref = sign(q) * 100 * pct          # -100..100；q == 0 时 tau_ref = 0
reversal_index = max(0, -tau_ref) / 100    # 0..1
```

- `sign(q)`：`q > 0` 为 `+1`，`q < 0` 为 `-1`，`q == 0` 为 `0`。
- 并列用 0.5 修正。
- `exclude_self` 推荐默认 **开启**：参考查询本身来自 Touchstone 签名，若该参考查询的来源药物与待评药物相同，其自身 NCS 往往接近极值，会把 tau 抬高。官方参考分布是否剔除同药物需要确认（见第 10 节）；该开关写入 `meta.json` 与 `ref_version`。
- `MIN_REF=100` 以下的药物返回 `null`，前端显示“参考不足”，**不回退到旧查询内百分位**，避免混用两种尺度。
- 与官方的对应：`tau = sign × 100 × P(|ref_ncs| < |q_ncs|)`，即任务附录二方案 A 的定义。

`tau_score`（旧字段）继续保留并计算：使用本次查询的 Touchstone summary NCS 按旧公式算百分位。它只用于兼容旧前端/导出，不再作为主排序依据，文档与 API 注释标记为 deprecated。注意：由于 NCS/聚合已切换为新算法，旧 `tau_score` 的数值会与线上历史值不同，这是预期变化。

---

## 4. 参考查询集构造

### 4.1 参考查询来源

优先使用 `touchstone_score.gctx` 中的真实 Touchstone 签名（GSE92742）。

- 资格：`pert_type in {trt_cp, trt_sh, trt_sh.cgs}`；排除 `ctl_vehicle`、`ctl_vector`；`trt_oe` 默认排除（配置 `REF_INCLUDE_OE=0`）。
- 基因空间：必须与线上一致。两种模式：
  - `gene_space=full12328`：用 `fast_matrix.npy` + 全部 12,328 基因；
  - `gene_space=landmark978`：用 L7a 的按签名 memmap + 978 landmark 基因（推荐，与官方一致）。
- 去重：同一 `(pert_id, cell_id, pert_idose, pert_itime)` 只保留一条（Touchstone 有 X1/X2/X3 等同条件重复），用 `sha256(f"{seed}:{sig_id}")` 最小者，避免近重复参考查询放大同一实验。
- 有效签名：向量中至少 `MIN_NON_NULL=100` 个非空值；至少能取出 `top_n=150` 个上调和 150 个下调基因。

### 4.2 抽样设计（R = 2000 + 400）

| 组 | 数量 | 用途 |
|---|---:|---|
| 真实 Touchstone 参考 | 2,000 | 计算 `tau_ref`；基因列表由 Touchstone 签名导出 |
| 随机基因集参考 | 400 | 从可用基因空间均匀抽取 150 上调 + 150 下调（上下调不重叠），用于空校准、诊断、检查 tau 的均匀性；**不参与 tau 计算** |

分层与配额：

- 按 `(cell_id, pert_type)` 分层；
- 按各层有效签名数比例分配 2,000 个名额；
- 单层最多占 5%（100 条），避免 MCF7/PC3 等大细胞系主导；
- 有效签名数 ≥5 的层至少 1 条；不足 5 条的层合并到 `pert_type` 层或全局池；
- 若有效分层签名总数不足 2,000，取全部，并把随机参考补到总行数 2,400；
- 随机种子固定 `20261017`，抽样结果写入 `ref_queries.tsv`，可完全复现。

如果服务器上没有 Touchstone 数据（本次不适用，作为备选方案保留）：

- 从 GSE92742 中选 `is_touchstone=1` 的 CGS 与化合物签名；
- 每个签名取表达量最高的 150 个基因作为上调、最低的 150 个作为下调；
- 再补 400 个随机基因集（从可用基因空间均匀抽 150+150，去重、上下调不重叠）；
- 其余流程相同。

### 4.3 每条参考查询的基因列表

```text
输入：参考签名向量 x（长度 G = 12328 或 978）
1. 取有限值基因集合 V
2. up   = V 中 x 值最高的 top_n=150 个基因（x > 0 优先；不足时用剩余最高值补足）
3. down = V 中 x 值最低的 top_n=150 个基因（x < 0 优先；不足时用剩余最低值补足）
4. 去掉 up/down 交集（交集基因从两侧删除）
5. 若 |up| < 10 或 |down| < 10，丢弃该参考签名并计数
6. 记录 up/down 基因 ID 的排序后 sha256，供复现与审计
```

注意：参考查询的基因列表来自 Touchstone 签名本身；随后用同一套 WTCS/NCS/聚合流程扫描**完整业务库**（473,647 条签名），得到该参考查询下每个药物的 NCS，再聚合为一行 `ref_ncs`。

---

## 5. 预计算脚本 `scripts/02_build_reference.py`

### 5.1 命令行接口

```bash
python scripts/02_build_reference.py \
  --matrix /srv/cmap/data/l1000_landmark_sig_major.npy \
  --matrix-layout sig_major \
  --col-ids /srv/cmap/data/col_sig_ids.csv \
  --row-ids /srv/cmap/data/landmark_gene_ids.csv \
  --touchstone-dir /srv/cmap/touchstone_data \
  --out /srv/cmap/reference/ts92742-r2000-v1 \
  --gene-space landmark978 \
  --n-ref 2000 \
  --n-random 400 \
  --top-n 150 \
  --workers 16 \
  --chunk-size 20000 \
  --seed 20261017 \
  --exclude-self \
  --resume
```

兼容现有数据的回退命令（无 L7a）：

```bash
python scripts/02_build_reference.py \
  --matrix /srv/cmap/cmap_data/fast_matrix.npy \
  --matrix-layout gene_major \
  --col-ids /srv/cmap/cmap_data/col_sig_ids.csv \
  --row-ids /srv/cmap/cmap_data/row_gene_ids.csv \
  --touchstone-dir /srv/cmap/touchstone_data \
  --out /srv/cmap/reference/ts92742-full12328-r2000-v1 \
  --gene-space full12328 \
  --n-ref 2000 --n-random 400 --top-n 150 \
  --workers 32 --chunk-size 5000 --seed 20261017 --exclude-self --resume
```

### 5.2 输入

| 输入 | 必需 | 说明 |
|---|---|---|
| `--matrix` | 是 | 业务库表达矩阵 memmap；`sig_major` 为 `(n_sig, n_gene)`，`gene_major` 为 `(n_gene, n_sig)` |
| `--matrix-layout` | 是 | `sig_major`（L7a）或 `gene_major`（现有 `fast_matrix.npy`） |
| `--col-ids` | 是 | 签名 ID 顺序，必须与矩阵签名轴一致 |
| `--row-ids` | 是 | 基因 ID 顺序，必须与矩阵基因轴一致 |
| `--touchstone-dir` | 是 | 含 `touchstone_siginfo.txt`、`touchstone_sig_ids.txt`、`touchstone_score.gctx`（仅取基因列表时需要读取 gctx） |
| `--gene-space` | 是 | `landmark978` 或 `full12328`，写入 meta，运行时必须匹配 |
| `--n-ref` / `--n-random` | 否 | 默认 2000 / 400 |
| `--top-n` | 否 | 默认 150 |
| `--workers` | 否 | 进程数，默认 `min(16, cpu_count())` |
| `--chunk-size` | 否 | 每次打分加载的签名数；`gene_major` 建议 5000，`sig_major` 建议 20000 |
| `--seed` | 否 | 抽样与去重种子，默认 20261017 |
| `--exclude-self` | 否 | 是否在 tau 读取时剔除同药物参考（只写入 meta，运行时生效） |
| `--resume` | 否 | 跳过已有 `.done` 分片 |
| `--use-rank-cache` | 否 | 可选：预生成每列基因秩，显著加速（见 5.5） |

### 5.3 输出目录

```text
<out>/
├── ref_ncs.npy          # float32, C-order, shape = (n_ref + n_random, n_pert)
│                        # 行 0..n_ref-1 = 真实 Touchstone 参考；其后 = 随机基因集参考
├── pert_index.csv       # n_pert 行，列：pert_idx, pert_iname, canonical_pert_id,
│                        #              pert_type, pert_types, n_instances, cell_count
├── ref_queries.tsv      # n_ref + n_random 行，列：ref_idx, kind, source_sig_id,
│                        #              pert_id, pert_iname, pert_type, cell_id, dose,
│                        #              time, up_gene_hash, down_gene_hash, n_up, n_down
├── meta.json            # 版本、参数、维度、校验和、软件 commit
├── qa.json              # 每行统计、NaN/常量列、分层覆盖、回退计数
└── SHA256SUMS           # ref_ncs.npy / pert_index.csv / ref_queries.tsv / meta.json
```

### 5.4 `meta.json` 字段

```json
{
  "ref_version": "ts92742-r2000-v1",
  "created_at": "2026-10-17T00:00:00+08:00",
  "source_dataset": "GSE92742",
  "source_touchstone_dir": "touchstone_data",
  "gene_space": "landmark978",
  "matrix_layout": "sig_major",
  "n_library_signatures": 473647,
  "n_genes": 978,
  "n_pert": 21000,
  "n_ref": 2000,
  "n_random": 400,
  "top_n": 150,
  "seed": 20261017,
  "min_non_null": 100,
  "min_ref_queries": 100,
  "exclude_self": true,
  "ncs_version": "ncs-strat-v1",
  "aggregation_version": "cell-q33q67-v1",
  "matrix_sha256": "<sha256 of matrix file or header>",
  "ref_ncs_sha256": "<sha256>",
  "scripts_commit": "<git commit of cmap-l1000>"
}
```

版本规则：

- `ref_version` 一旦发布不可原地修改；
- 任一条件变化必须新版本：源数据（92742/2020）、基因空间（978/12328）、库签名集合、`top_n`、NCS/聚合算法版本、`exclude_self`、抽样种子；
- API 返回的 `ref_version` 必须与运行时加载的 `meta.json` 一致；不一致时服务拒绝启动（或按 `CMAP_REF_REQUIRED=0` 降级为 legacy）。

### 5.5 并行方式与断点续跑

- 用 `multiprocessing.Pool(processes=--workers)`，每个 worker 独立以只读方式 `np.memmap` 打开矩阵，避免跨进程共享大数组。
- 任务单位：一个参考查询。worker 完成一条后写出 `shards/shard_{ref_idx:05d}.npy`（`float32, shape=(n_pert,)`）和同名 `.done`。
- 主进程按 `ref_idx` 顺序汇总到最终的 C-order `ref_ncs.npy`，保证相同输入/相同 seed 下逐字节一致（与 worker 数无关）。
- 每完成 50 条打印进度并 `flush`；支持 `--resume` 跳过 `.done`。
- 失败重试 1 次；仍失败写入 `qa.json.failed_refs`，全量结束后若有失败，脚本以非零码退出，不产出 `SHA256SUMS`。

### 5.6 可选加速：秩缓存

WTCS 的主要开销是对每个候选签名的基因排序。可先离线生成一份每列基因秩矩阵：

- `rank_matrix.npy`：`uint16`，`(n_sig, n_gene)`；978 landmark 时 473,647 × 978 × 2 B ≈ **926 MB**；12,328 时约 11.7 GB（不推荐）。
- 每条参考查询只需在秩矩阵上做指示向量 gather + 两次 `cumsum`，无需 `argsort`。
- 生成秩缓存耗时约 1–2 小时（978）；之后每条参考查询约 5–15 秒/核（估算，需实测）。
- 秩缓存作为 `reference/rank_cache/<hash>/` 独立产物，可被未来 other scorers 复用；不写入 `ref_ncs` 版本键（它只影响速度，不影响结果；但 must 用同一浮点比较/排序规则，QA 需比对无缓存结果）。

### 5.7 预计耗时

| 配置 | 单条参考查询 | R=2000 单核 | 16 核 | 32 核 |
|---|---:|---:|---:|---:|
| 现有 `fast_matrix`（12,328 行、gene_major、无秩缓存） | 8–20 分钟 | 11–28 天 | 17–42 小时 | 8–21 小时；考虑 I/O 争用与长尾，**报告估计 1–3 天** |
| L7a `sig_major` 978 + 秩缓存 | 5–15 秒 | 3–8 小时 | **20–60 分钟** | 10–30 分钟 |
| L7a `sig_major` 978、无秩缓存 | 15–40 秒 | 8–22 小时 | 30–90 分钟 | 15–45 分钟 |

说明：

- 上表为预计算**参考集**的耗时，不是单次用户查询耗时。用户查询仍是一次全库 WTCS，通常 1–10 分钟（取决于当前实现与数据布局）。
- 上表按每核独占 I/O 估算；共享 NFS/机械盘会放大长尾。实际排期以 `--n-ref 100` 的 smoke 实测线性外推。
- 磁盘：`ref_ncs.npy` = 2,400 × n_pert × 4 B。n_pert 约 20,000–22,000 时约 **184–202 MB**；分片临时空间同量级；秩缓存约 0.9 GB。
- 内存：每个 worker 只驻留一个 chunk（`chunk_size × n_gene × 4 B`，20,000×978×4≈78 MB）和一条查询的中间结果；16 worker 约 2–4 GB，可接受。

---

## 6. 运行时读取层 `app/core/reference_store.py`

### 6.1 接口

```python
# Python 3.8 兼容
from typing import Dict, List, Optional, Sequence
import json
import os
import numpy as np


class ReferenceStore:
    """只读加载 ref_ncs，按需计算 tau_ref。"""

    _instance = None  # type: Optional["ReferenceStore"]

    def __init__(self, ref_dir: str, mmap_mode: str = "r") -> None:
        self.ref_dir = ref_dir
        with open(os.path.join(ref_dir, "meta.json"), "r", encoding="utf-8") as f:
            self.meta = json.load(f)  # type: Dict
        self.version = str(self.meta["ref_version"])  # type: str
        self.n_ref = int(self.meta["n_ref"])
        self.exclude_self = bool(self.meta.get("exclude_self", True))
        self.min_ref = int(self.meta.get("min_ref_queries", 100))
        self._matrix = np.load(
            os.path.join(ref_dir, "ref_ncs.npy"),
            mmap_mode=mmap_mode,
        )  # type: np.ndarray
        self._pert_to_idx = {}  # type: Dict[str, int]
        self._load_pert_index()

    def _load_pert_index(self) -> None:
        import csv
        path = os.path.join(self.ref_dir, "pert_index.csv")
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                self._pert_to_idx[row["pert_iname"]] = int(row["pert_idx"])

    def has_pert(self, pert_iname: str) -> bool:
        return pert_iname in self._pert_to_idx

    def tau_ref_for(self, pert_iname: str, query_ncs: float,
                    exclude_pert: Optional[str] = None) -> Optional[float]:
        idx = self._pert_to_idx.get(pert_iname)
        if idx is None or query_ncs is None:
            return None
        col_all = np.asarray(self._matrix[: self.n_ref, idx], dtype=np.float64)
        keep = np.isfinite(col_all)
        if self.exclude_self and exclude_pert is not None:
            # 参考行与来源药物的对应关系由 ref_queries.tsv 预先编码为布尔掩码
            self_mask = self._self_mask(exclude_pert)
            if self_mask is not None:
                keep = keep & (~self_mask[: self.n_ref])
        col = col_all[keep]
        n = col.size
        if n < self.min_ref:
            return None
        abs_col = np.abs(col)
        abs_q = abs(float(query_ncs))
        lt = int(np.count_nonzero(abs_col < abs_q))
        eq = int(np.count_nonzero(abs_col == abs_q))
        pct = (lt + 0.5 * eq) / float(n)
        if query_ncs > 0:
            return 100.0 * pct
        if query_ncs < 0:
            return -100.0 * pct
        return 0.0

    @staticmethod
    def reversal_index(tau_ref: Optional[float]) -> Optional[float]:
        if tau_ref is None:
            return None
        return max(0.0, -float(tau_ref)) / 100.0

    def close(self) -> None:
        self._matrix = None
```

实现要点：

- 只为**最终返回的 top/bottom 各 150 条**计算 `tau_ref`（每条约 2,000 次比较），总开销 < 1 ms 量级；不对全部 2 万药物做全量 tau。
- `self._self_mask(pert)` 从预先生成的稀疏掩码/位图读取（`ref_queries.tsv` 的 `pert_iname` 与列对应），避免运行时扫描 2,400 行文本；若 `exclude_self=False` 可完全跳过。
- 单例懒加载；`mmap_mode="r"`；启动时校验 `ref_ncs.shape == (n_ref + n_random, n_pert)`、`dtype == float32`，失败按 `CMAP_REF_REQUIRED` 决定抛错或降级。
- 该层不依赖 pandas，启动开销 < 100 ms。

### 6.2 配置新增（`app/config.py`）

```python
# ============ 方案 A：Touchstone 参考集 ============
SCORING_MODE = os.getenv("CMAP_SCORING_MODE", "legacy")       # legacy | tau_ref_v1
TOUCHSTONE_DIR = os.getenv(
    "CMAP_TOUCHSTONE_DIR", os.path.join(PROJECT_ROOT, "touchstone_data")
)
REF_DIR = os.getenv(
    "CMAP_REF_DIR", os.path.join(PROJECT_ROOT, "reference", "ts92742-r2000-v1")
)
REF_REQUIRED = os.getenv("CMAP_REF_REQUIRED", "0") == "1"
REF_MIN_QUERIES = int(os.getenv("CMAP_REF_MIN_QUERIES", "100"))
TAU_STRONG = float(os.getenv("CMAP_TAU_STRONG", "-90"))
TAU_MEDIUM = float(os.getenv("CMAP_TAU_MEDIUM", "-80"))
NCS_INCLUDE_OE = os.getenv("CMAP_NCS_INCLUDE_OE", "0") == "1"
```

`TOUCHSTONE_DIR` 改为可被环境变量覆盖，解决 D5 中的路径不一致；`TOUCHSTONE_GCTX_PATH`、`TOUCHSTONE_SIGINFO_PATH` 随之派生。

---

## 7. 代码改动清单（供实施参考，本任务不执行）

| 文件 | 改动 | 类型 |
|---|---|---|
| `scripts/02_build_reference.py` | 新增：参考查询构造、全库打分、NCS/聚合、分片、汇总、QA | 新增 |
| `scripts/02_build_rank_cache.py` | 可选新增：978 landmark 秩缓存 | 新增 |
| `app/core/reference_store.py` | 新增：读取 `ref_ncs`、计算 `tau_ref`/`reversal_index` | 新增 |
| `app/core/post_processor.py` | 重写 `_calculate_ncs`（正负分开、分层、回退）；重写 `_aggregate_by_perturbagen`（q33/q67）；新增 `_calculate_tau_ref`；旧 `_calculate_tau` 保留为 `tau_score` | 修改 |
| `app/config.py` | 新增参考集/开关/阈值配置；`TOUCHSTONE_DIR` 支持环境变量 | 修改 |
| `app/models/schemas.py` | `TauSearchResult` 增加 `tau_ref: Optional[float]`、`reversal_index: Optional[float]`、`ref_version: Optional[str]` | 修改（只加） |
| `app/api/tau_search.py` | top/bottom 两处 dict 增加三个字段；按 `tau_ref` 排序；结果不足时返回 null | 修改 |
| `index.html` | 表格主分数改为 `tau_ref` + 强弱标签，增加逆转指数列/提示；图表 tooltip 同步 | 修改 |
| `tests/test_post_processor_v2.py` | 新增：NCS 分层/回退、聚合分位、tau 并列与阈值 | 新增 |
| `tests/test_reference_store.py` | 新增：加载、缺列、min_ref、exclude_self、逆转指数 | 新增 |
| `tests/test_api_contract.py` | 新增/扩展：字段存在性、旧字段兼容、null 容忍 | 新增/扩展 |

依赖：不新增 Python 包（`numpy`、`pandas`、`h5py` 已在 `requirements.txt`）。Python 3.8 语法约束适用于所有新增/修改代码。

---

## 8. API 契约（只加字段）

### 8.1 Schema 变更

```python
# app/models/schemas.py（Python 3.8 兼容）
class TauSearchResult(BaseModel):
    rank: int
    pert_iname: str
    pert_type: str
    tau_score: float                 # 保留：旧查询内百分位（deprecated）
    summary_ncs: float
    best_wtcs: float
    cell_count: int
    best_cell_id: str
    best_dose: str
    is_touchstone: bool
    tau_ref: Optional[float] = None       # 新增：-100..100，绝对值越大连接越强
    reversal_index: Optional[float] = None  # 新增：max(0, -tau_ref)/100，0..1
    ref_version: Optional[str] = None     # 新增：参考集版本，如 ts92742-r2000-v1
```

### 8.2 响应示例

```json
{
  "query_up_count": 150,
  "query_down_count": 150,
  "top_results": [
    {
      "rank": 1,
      "pert_iname": "example-drug",
      "pert_type": "trt_cp",
      "tau_score": -91.3,
      "tau_ref": -94.8,
      "reversal_index": 0.948,
      "ref_version": "ts92742-r2000-v1",
      "summary_ncs": -2.41,
      "best_wtcs": -0.62,
      "cell_count": 14,
      "best_cell_id": "A375",
      "best_dose": "10 µM",
      "is_touchstone": true
    }
  ],
  "bottom_results": []
}
```

### 8.3 兼容性与降级

- 三个新字段均为 `Optional`，旧客户端忽略即可；旧字段含义不变（`tau_score` 数值会因 NCS/聚合升级而变化，需在发布说明中标注）。
- 参考集缺失：`SCORING_MODE=legacy` 时新字段返回 `null`，`ref_version=null`；`REF_REQUIRED=1` 时启动直接失败，避免静默降级。
- 排序：`top_results` 按 `tau_ref` 升序（`null` 排最后），`bottom_results` 按 `tau_ref` 降序；`rank` 在响应内重排。旧前端若只读 `tau_score` 仍能显示，但顺序会变化。
- CSV 导出（`app/api/export*.py`）：新增 `tau_ref`、`reversal_index`、`ref_version` 三列，保留旧列。

### 8.4 前端展示

- 主分数列标题：`逆转指数（Tau）`；显示 `tau_ref`（带符号，保留 1 位）与 `reversal_index`（3 位）。
- 强度标签（基于 `tau_ref`）：
  - `tau_ref <= -90`：强
  - `-90 < tau_ref <= -80`：中
  - `tau_ref > -80`：弱/无
- 等价写法（基于逆转指数）：`RI >= 0.90` 强、`0.80 <= RI < 0.90` 中。
- 注意任务原文“≤−90 强、≤−80 中”只能落在 `tau_ref` 尺度（`reversal_index` 是 0–1），实施时以前者为准；该歧义列入待确认项。
- 表格保留 `best_wtcs` 列，增加 tooltip 显示 `summary_ncs`、`ref_version`、参考样本数。
- 颜色：`tau_ref < 0` 为逆转（现有 `score-neg` 样式），`> 0` 为相似/加重（`score-pos`）。

---

## 9. 与 L7a 的依赖关系

### 9.1 依赖性质

- **功能上不阻塞**：方案 A 可以在现有 `fast_matrix.npy`（12,328 基因、gene-major）上完整实现，参考集与线上查询都使用 `gene_space=full12328`。
- **性能上强依赖**：全量 R=2000 的预计算在现有布局下 32 核约 1–3 天；L7a 的 `sig_major`（473,647 × 978，float32，约 1.8 GB）把每条参考查询的 I/O 从“随机读 23 GB”变为“顺序读 1.8 GB”，配合秩缓存可降到小时级。
- **口径上建议依赖**：官方 L1000 连接性打分使用 978 landmark 基因。使用 L7a 后，参考集与线上查询统一为 `landmark978`，与 CLUE 口径一致；不使用 L7a 时两者都必须是 `full12328`，不能一边 978、一边 12,328。

### 9.2 假定的 L7a 数据契约

C5 实施时按以下契约读取 L7a 产物（具体文件名以 L7a 文档为准，需在实施前对齐）：

```text
l1000_landmark_sig_major.npy   float32, C-order, shape=(n_sig, 978)
landmark_gene_ids.csv          978 行，列 gene_id，顺序 = 矩阵列顺序
col_sig_ids.csv                n_sig 行，列 sig_id，顺序 = 矩阵行顺序
meta.json                      dtype/order/shape/sha256/source
```

若 L7a 最终采用不同布局或分块，`02_build_reference.py` 的 `--matrix-layout` 与 `ReferenceStore` 不需要变，只需调整矩阵加载适配器。

### 9.3 排期建议

1. L7a 先合并（LMNA 侧共享数据层）；
2. C5 在 L7a 产物上做 `gene_space=landmark978` 的参考集与线上打分；
3. 若业务要求 C5 提前上线，可先用 `full12328` 出 `ref_version=ts92742-full12328-r2000-v1`，L7a 合并后再出 `landmark978` 版本并切换；两个版本的 tau 不可混用，切换时更新 `ref_version` 并重跑验证。

---

## 10. 迁移步骤（人工执行；本任务不执行）

### 阶段 0：决策与准备

1. 确认第 11 节的 D5 子项（数据版本、R、阈值、聚合方式、是否立项）。
2. 确认 L7a 排期；若 L7a 未就绪，选择 `full12328` 过渡版本。

### 阶段 1：数据搬迁（只读源，不在生产目录写）

```bash
# 查看源大小（只读）
ssh -i ~/.ssh/lmna_deploy keji@10.39.15.238 \
  "du -sh ~/cmap/temp/touchstone_data; df -h ~"

# 人工在构建机/暂存盘执行（示例；不要写 ~/cmap）
rsync -av --progress \
  keji@10.39.15.238:~/cmap/temp/touchstone_data/ \
  /srv/cmap/touchstone_data/

# 校验关键文件
ls -l /srv/cmap/touchstone_data/touchstone_score.gctx \
      /srv/cmap/touchstone_data/touchstone_siginfo.txt
wc -l /srv/cmap/touchstone_data/touchstone_sig_ids.txt   # 期望 293619
```

验收：文件大小与第 2.2 节一致；`touchstone_sig_ids.txt` 行数 293,619；`touchstone_siginfo.txt` 表头包含 `sig_id/pert_id/pert_iname/pert_type/cell_id`。

### 阶段 2：Smoke 预计算（R=100）

```bash
python scripts/02_build_reference.py \
  --matrix /srv/cmap/data/l1000_landmark_sig_major.npy \
  --matrix-layout sig_major \
  --col-ids /srv/cmap/data/col_sig_ids.csv \
  --row-ids /srv/cmap/data/landmark_gene_ids.csv \
  --touchstone-dir /srv/cmap/touchstone_data \
  --out /srv/cmap/reference/smoke-r100 \
  --gene-space landmark978 \
  --n-ref 100 --n-random 20 --top-n 150 \
  --workers 8 --seed 20261017 --exclude-self --resume
```

验收：

- `ref_ncs.npy` shape `(120, n_pert)`，dtype `float32`；
- `qa.json` 中 `nan_count == 0`、`failed_refs == []`、`constant_columns < 1%`；
- 随机参考行的 tau 分布近似均匀（见 12.4）；
- 与 `--workers 1` 的 5 条参考结果逐字节一致（确定性）。

### 阶段 3：全量预计算（R=2000）

```bash
nohup python scripts/02_build_reference.py \
  --matrix /srv/cmap/data/l1000_landmark_sig_major.npy \
  --matrix-layout sig_major \
  --col-ids /srv/cmap/data/col_sig_ids.csv \
  --row-ids /srv/cmap/data/landmark_gene_ids.csv \
  --touchstone-dir /srv/cmap/touchstone_data \
  --out /srv/cmap/reference/ts92742-r2000-v1 \
  --gene-space landmark978 \
  --n-ref 2000 --n-random 400 --top-n 150 \
  --workers 16 --chunk-size 20000 \
  --seed 20261017 --exclude-self --resume \
  > /srv/cmap/logs/build_ref_$(date +%Y%m%d_%H%M).log 2>&1 &
```

验收：`SHA256SUMS` 生成；`meta.json` 的 `n_pert`、`n_ref`、`gene_space` 与预期一致；抽查 20 个药物列的非空率 > 99%。

### 阶段 4：代码部署（开关默认关闭）

```bash
export CMAP_SCORING_MODE=legacy
export CMAP_REF_DIR=/srv/cmap/reference/ts92742-r2000-v1
export CMAP_REF_REQUIRED=0
# 部署新代码，不重启生产服务；由人工在窗口期执行
```

验收：旧接口响应、旧前端展示与部署前一致；`tau_ref` 字段存在但为 `null`（legacy 模式）。

### 阶段 5：影子模式

- 内部查询同时计算 `tau_score` 与 `tau_ref`，只记录日志，不改变响应排序；
- 对比 100 条真实查询的 top-50 重叠率与自连接结果；
- 发现异常可随时保持 `legacy`，无需回滚数据。

### 阶段 6：切换

```bash
export CMAP_SCORING_MODE=tau_ref_v1
export CMAP_REF_REQUIRED=1
```

- 灰度：先内部用户/10% 流量，观察 1 周；
- 全量：更新前端主分数与导出列；发布说明标注“分数尺度变化、不可与历史 tau 直接比较”。

### 阶段 7：回滚

```bash
export CMAP_SCORING_MODE=legacy
export CMAP_REF_REQUIRED=0
```

参考集目录保留不动；API 新字段返回 `null`；旧字段与旧排序恢复。无需重建数据。

---

## 11. 验证方案

### 11.1 单元测试（合成数据）

| 用例 | 构造 | 断言 |
|---|---|---|
| NCS 正负分别归一 | 两个细胞系，各含正/负 Touchstone，正负均值不同 | 正分除以 `pos_denom`、负分除以 `neg_denom`，与手算一致 |
| NCS 分层 | 同一细胞系 `trt_cp` 与 `trt_sh.cgs` 分母不同 | 两层分别归一，不串层 |
| NCS 回退链 | 某层 < 10 条 | 依次回退到 `pert_type`、`cell_id`、全局，`ncs_fallback` 标记正确 |
| 聚合 q33/q67 | 某药某细胞系 3 条负分、3 条正分 | 负取 q33、正取 q67；跨细胞系取最大绝对值 |
| 聚合溯源 | 分位值不对应真实实例 | 选择最近真实实例的 `best_wtcs/cell/dose` |
| tau 公式 | 已知 `ref_ncs` 列与 `q` | `tau_ref` 与手算百分位一致；`q=0` 返回 0 |
| tau 并列 | 参考值含与 `|q|` 相等的项 | 0.5 并列修正 |
| min_ref | `n_eff < 100` | 返回 `null`，不回退 |
| exclude_self | 参考行来源药物与查询药物同名 | 该行被剔除，`n_eff` 减 1 |
| 逆转指数 | `tau_ref=-94.8` / `+50` / `null` | 0.948 / 0 / `null` |

### 11.2 参考集确定性

- 同一 `--seed`、同一输入、`--workers 1` 与 `--workers 16` 的 `ref_ncs.npy` SHA256 必须一致；
- 重跑 smoke 两次，`ref_queries.tsv` 逐字节一致。

### 11.3 自连接（同一药物、不同细胞系）

构造：选 20 个在 Touchstone 中覆盖 ≥3 个细胞系的药物；对每个药物，用细胞系 A 的签名取 top150 上/下调作为查询，运行完整线上流程，观察该药物在结果中的位置与 `tau_ref`。

评估时必须排除源签名本身及其同 `distil_id` 的技术重复（它们与查询基因集完全同源，会被人为推到第 1 名）；保留该药物在其他细胞系、其他剂量/时间下的实例，这才是“自连接”要检验的信号。

验收：

- 该药物在 20,000+ 药物中的排名中位数 ≤ 50；
- ≥70% 的案例进入 top 100；
- 自身 `tau_ref` 中位数 ≤ −80；
- 与 100 个随机药物的 `tau_ref` 相比，AUC ≥ 0.9；
- 用细胞系 B、C 重复，结论一致（检验跨细胞系稳健性）。

### 11.4 与 C3 FDR 的一致性

- 在同一批 20–50 条真实查询上，分别得到 C3 的 `p_value/fdr` 与 C5 的 `tau_ref`；
- 药物级 join 键为 `pert_iname`；
- 验收：
  - `tau_ref` 与 `-log10(fdr)` 的 Spearman ρ ≥ 0.4（在同一批被检验药物中）；
  - `tau_ref <= -90` 的药物中 `fdr < 0.1` 的比例 ≥ 背景比例的 2 倍；
  - 两套方法各自 top-50 的重叠 ≥ 25 个（允许口径差异）。
- 说明：C3 未合并前此项只能做离线原型；合并后作为发布门槛。

### 11.5 分布与空校准

- 用 400 条随机签名参考行（`kind=random`）检查：对随机查询，`tau_ref` 应近似均匀分布在 [−100, 100]（KS 检验 p > 0.01），`reversal_index` 均值约 0.5；
- 真实 Touchstone 参考行的 `tau_ref` 在药物间不应出现大面积 `±100` 饱和；若饱和比例 > 5%，检查 `n_eff` 与并列处理。

### 11.6 回归与性能

- 旧字段 `tau_score/summary_ncs/best_wtcs/cell_count/best_cell_id/best_dose/is_touchstone` 全部存在且类型不变；
- API p95 延迟相比 legacy 增加 < 20%（参考集 mmap 加载 < 100 ms，tau 计算 < 10 ms）；
- CSV 导出列数增加 3 列，旧列顺序不变；
- 前端在 `tau_ref=null` 时显示“参考不足”，不报错。

---

## 12. 工作量估算

单位：人日（1 人）；不含 L7a 本身。

| 编号 | 工作项 | 人日 | 说明 |
|---|---|---:|---|
| W0 | D5 收尾、数据搬迁与校验（人工/运维） | 0.5 | 14.9 GB（约 13.9 GiB） 拷贝与校验 |
| W1 | 参考查询构造、去重、分层抽样、QA | 2–3 | 含 `ref_queries.tsv` 与覆盖报告 |
| W2 | `scripts/02_build_reference.py`（分片、续跑、汇总、校验和） | 4–6 | 含 `gene_major`/`sig_major` 两种布局 |
| W3 | 可选秩缓存 `02_build_rank_cache.py` | 1–2 | 978 landmark 专用 |
| W4 | `app/core/reference_store.py` | 2–3 | 含 exclude_self 掩码、降级 |
| W5 | `post_processor` 三个函数重写 + 旧 tau 保留 | 4–5 | NCS 分层/回退、聚合分位、tau_ref |
| W6 | 配置、schema、API、CSV 导出 | 1–2 | 只加字段 |
| W7 | 前端表格/标签/图表/tooltip | 2–3 | 含 null 与空态 |
| W8 | 单元测试、自连接、FDR 一致性、回归 | 4–6 | 依赖 C3 的部分可后置 |
| W9 | Smoke + 全量预计算运行与验收 | 2–3 | 不含机器时间 |
| **合计** | | **23–34 人日** | 约 5–7 周（单人）；可与 L7a 并行部分约 1 周 |

一次性机器时间：

| 场景 | 机器时间 |
|---|---|
| Smoke R=100（978+秩缓存，8 核） | 20–60 分钟 |
| 全量 R=2000（978+秩缓存，16 核） | 1–3 小时 |
| 全量 R=2000（978 无缓存，16 核） | 0.5–1.5 天 |
| 全量 R=2000（12,328 现有布局，32 核） | 1–3 天（报告估计） |

年度维护：数据/算法不变则无需重算；更换库版本或基因空间时重跑一次，约 1 人日 + 上述机器时间。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 参考集细胞系/扰动类型覆盖不均 | tau 对少见细胞系偏差 | 分层抽样、单层 5% 上限、`qa.json` 报告覆盖；对 `n_eff` 不足返回 null |
| 自匹配泄漏 | 同药物 tau 虚高 | `exclude_self=1`；自连接验证 |
| 聚合口径偏离官方 | 与 CLUE 数值不可直接对比 | 默认 `cell_q33q67_v1`，保留 `max_abs_v1` A/B；文档明确口径 |
| 基因空间不一致 | 参考集与线上分数不可比 | `ref_version` 编码 `gene_space`；启动强校验；不一致拒绝加载 |
| 数据版本漂移 | 新旧分数混用 | 版本目录不可变；API 返回 `ref_version`；前端提示 |
| 无 L7a 时预计算过慢 | 上线延期 | 先出 `full12328` 过渡版；或分批增量构建；把 L7a 作为正式上线门槛 |
| 分数尺度变化引起用户困惑 | 投诉/误读 | 前端同时显示 tau 与逆转指数；发布说明；历史查询不重算 |
| 参考数据许可证/再分发 | 合规风险 | 数据来自公开 GEO GSE92742，仅内部使用；不随代码仓库提交 14.9 GB（约 13.9 GiB） 原始数据；`ref_ncs` 为派生统计量，按机构要求评估 |
| 14.9 GB（约 13.9 GiB） 数据搬迁失败/磁盘不足 | 预计算阻塞 | 阶段 1 先 `df -h`；预留 ≥20 GB；校验 SHA/行数 |

---

## 14. 待人工确认（D5 及实施决策）

| 编号 | 决策点 | 建议 | 影响 |
|---|---|---|---|
| D5-a | 参考集用 GSE92742 还是 LINCS2020 | **GSE92742（现有数据）** | 决定 `ref_version` 与是否需要下载新数据 |
| D5-b | 是否批准把 `~/cmap/temp/touchstone_data`（14.9 GB（约 13.9 GiB））搬到项目 `touchstone_data/` 或配置环境变量 | 搬迁/软链，生产目录保持只读 | 不解决则代码读不到数据 |
| D5-c | R 与随机参考数：2000 + 400 | 同意；smoke 用 100 + 20 | 影响预计算时间与 tau 分辨率 |
| D5-d | `exclude_self` 是否默认开启 | **开启**（避免自匹配泄漏） | 影响 tau 数值与官方可比性 |
| D5-e | 聚合口径：`cell_q33q67_v1` 还是官方 `max_abs_v1` | 默认前者，A/B 后定 | 影响药物级分数与排名 |
| D5-f | 强弱阈值：`tau_ref <= -90` 强、`<= -80` 中；`reversal_index` 用 0.90/0.80 | 同意 | 影响前端标签 |
| D5-g | 是否立项实施、与 L7a 的排期 | L7a 先行；C5 随后（或先出 full12328 过渡版） | 决定是否进入开发 |
| D5-h | 旧 `tau_score` 是否保留导出 | 保留并标 deprecated，至少一个版本周期 | 影响兼容与前端迁移 |

---

## 15. 验收清单（对应任务要求逐条）

| 任务要求 | 本文章节 | 状态 |
|---|---|---|
| 1. D5：服务器是否有 Touchstone 数据；没有时如何构造参考集 | §2（实测：有，14.9 GB（约 13.9 GiB），293,619 签名，76 细胞系）；§4.2 备选构造 | 完成 |
| 2. `scripts/02_build_reference.py`：输入、输出 `ref_ncs[R × n_pert]` 格式与版本号、并行方式、耗时；依赖 L7a | §5（CLI、输入输出、meta、并行/续跑、耗时表）；§9 L7a | 完成 |
| 3. `_calculate_ncs`、`_aggregate_by_perturbagen`、`_calculate_tau` 新算法（伪代码 + 官方对应） | §3.3、§3.4、§3.5；§7 改动清单 | 完成 |
| 4. API 只加 `tau_ref`、`reversal_index`、`ref_version`；前端主分数 + 强度标签 | §8（schema、JSON、兼容、前端） | 完成 |
| 5. 验证：跨细胞系自连接、C3 FDR 与 tau_ref 一致性 | §11.3、§11.4 | 完成 |
| 统一符号约定：负=逆转；逆转指数 0–1 | §3.1、§3.5 | 完成 |
| 只出文档、不改代码 | 全文；本分支仅新增 `docs/design/C5-touchstone-tau.md` 与 `deliveries/task-C5.md` | 完成 |
| Python 3.8 语法 | §6.1、§8.1 示例均为 3.8 兼容（`typing.Optional/List/Dict`，不含 3.9+ 的联合类型与字典合并语法） | 完成 |

---

## 16. 附录

### 16.1 与报告“任务二·1”的对应

- 报告指出 tau 是查询内相对排名、NCS 统一分母、聚合取极值、Touchstone 配置未使用、医务人员反馈“最高 0.6”很可能来自原始 WTCS。本方案分别用 `ref_ncs` 绝对参考分布、正负分层 NCS、细胞系内分位聚合、接通 `TOUCHSTONE_*` 配置解决；前端主分数改为可跨查询比较的 `tau_ref`/逆转指数，避免与原始 WTCS 的 0.6 量级混淆。
- 方案 A 与方案 B（C3 随机签名 null/FDR）互补：B 提供显著性，A 提供绝对效应尺度；推荐 B 先上线，A 随后。

### 16.2 关键文件路径

- 设计文档：`docs/design/C5-touchstone-tau.md`
- 交付说明：`deliveries/task-C5.md`
- 计划新增：`scripts/02_build_reference.py`、`app/core/reference_store.py`
- 计划修改：`app/core/post_processor.py`、`app/config.py`、`app/models/schemas.py`、`app/api/tau_search.py`、`index.html`
- 数据：`touchstone_data/`（服务器现有于 `~/cmap/temp/touchstone_data/`）、`reference/ts92742-r2000-v1/`

### 16.3 术语与阈值速查

```text
tau_ref   : -100..100；负=逆转，正=相似/加重
RI        : max(0, -tau_ref)/100；0..1；越大越逆转
强        : tau_ref <= -90  <=>  RI >= 0.90
中        : -90 < tau_ref <= -80  <=>  0.80 <= RI < 0.90
弱/无     : tau_ref > -80  <=>  RI < 0.80
```
