# task-D1 · 数据完整性防线（cmap-l1000 侧）

任务ID / 分支 / 基线提交：`D1` / `feat/D1-integrity` / `origin/master` @ `40dfe9c`

## 结论摘要

1. **防线1 已接入 cmap**：新增共享模块 `app/core/lincs_integrity.py`
   （与 LMNA `backend/lincs_integrity.py` 内容完全一致，文件头已注明同步要求；
   Python 3.8 兼容，已用 3.8.20 解释器验证 import 与全部测试）。
2. 接入点与任务卡一致：
   - `app/core/metadata_index.py::_build_sig_index`：构建 sig_id→列索引 映射**之前**
     调用 `check_startup`；
   - `app/core/matrix_store.py::__init__`：打开 memmap **之前**调用 `check_startup`。
3. `LINCS_INTEGRITY_MODE=gctx|fingerprint|off`，**默认 fingerprint**；
   花名册或矩阵任何不一致抛 `RuntimeError` 拒绝加载（fail fast）；
   `off` 仅供测试，启用时打 WARNING。
4. `tests/make_synthetic_data.py` 现在同时生成 `integrity.json`
   （按文件路径动态加载共享模块，避免在环境变量设置前 import `app.config`），
   因此既有 39 个测试在默认 fingerprint 模式下全部照常通过。
5. cmap 侧只接入防线1（任务卡范围）；防线2（生物学自检/判档）在 LMNA 侧实现。

## 改动文件

| 文件 | 改动 |
|---|---|
| `app/core/lincs_integrity.py` | 新增。共享模块（与 LMNA 侧逐字节一致） |
| `app/core/metadata_index.py` | 新增 import（`ROW_NAMES_PATH`、`MATRIX_PATH`、`check_startup`）；`_build_sig_index` 起始处完整性检查 |
| `app/core/matrix_store.py` | 新增 import（`COL_NAMES_PATH`、`ROW_NAMES_PATH`、`check_startup`）；memmap 打开前完整性检查 |
| `tests/make_synthetic_data.py` | 生成数据后写 `integrity.json`（importlib 按路径加载共享模块） |
| `tests/test_integrity.py` | 新增，8 个用例（见下） |
| `deliveries/task-D1.md` | 本文件 |

## 自测验收

### [x] cmap 现有 39 个测试 + 新增完整性测试全部通过

`pytest -q`：**47 passed, 1 skipped**（39 原有 + 8 新增；1 skipped 为基线既有）。
证据：`D:\agent-workspace\deliveries\task-D1\cmap_pytest_full.txt`。

新增 `tests/test_integrity.py` 8 用例：

| 用例 | 内容 |
|---|---|
| `test_correct_data_loads` | 正确数据下 MetadataIndex / MatrixStore 正常加载（默认 fingerprint 模式） |
| `test_col_roster_other_version_rejected` | 列花名册换成另一版本顺序（集合相同、逆字典序）→ `RuntimeError` |
| `test_col_roster_shuffled_rejected` | 列花名册随机打乱 → `RuntimeError` |
| `test_col_roster_one_off_rejected` | 列花名册只错 1 位 → `RuntimeError` |
| `test_row_roster_shuffled_rejected` | 行花名册随机打乱 → `RuntimeError` |
| `test_row_roster_missing_line_rejected` | 行花名册少一行 → `RuntimeError` |
| `test_matrix_swap_same_shape_rejected` | 矩阵被换成同形状另一文件 → `RuntimeError` |
| `test_off_mode_passes_with_warning` | off 模式放行（复现旧行为）但 WARNING「仅供测试」 |

说明：5 种花名册 × 行/列 × 2 模式的完整矩阵（20 用例）在 LMNA 侧
`backend/tests/test_integrity.py`（两仓库共享同一模块，语义一致）；cmap 侧聚焦接入点验收。

### [x] 共享模块一致性

`diff D:\agent-workspace\worktrees\task-D1-lmna\backend\lincs_integrity.py
D:\agent-workspace\worktrees\task-D1-cmap\app\core\lincs_integrity.py` → 无差异。

### [x] Python 3.8 兼容

测试解释器 `D:\agent-workspace\venvs\cmap-c0-38\Scripts\python.exe`（3.8.20）跑全套通过；
共享模块无 `list[str]` / `X | None` 等新语法。

## 部署注意

- 与 LMNA 共用同一数据目录与 `integrity.json`：服务器部署窗口由人执行
  `python scripts/fix_col_names.py --data-dir ~/cmap/cmap_data --check --write-fingerprint`
  （在 LMNA 仓库的 scripts 下）生成指纹后，cmap 默认 fingerprint 模式即可启动。
  回滚 = 删除 `integrity.json` 并设 `LINCS_INTEGRITY_MODE=gctx`（或临时 `off`，会有 WARNING）。
- 数据目录缺 `integrity.json` 时，MetadataIndex / MatrixStore 首次加载即抛
  `RuntimeError` 并给出修复命令——这是故意的 fail fast。

## 主agent验收命令

```bash
cd <cmap-l1000 worktree> && \
  D:\agent-workspace\venvs\cmap-c0-38\Scripts\python.exe -m pytest tests -q
# 期望：47 passed, 1 skipped（tests/test_integrity.py 8 个用例全过）
```

## 待人工确认项

- 🧑‍⚖️ Q2 已按任务包默认建议实现为 **fingerprint**；切换 gctx 只需环境变量。

## 发现但未处理项

- `MetadataIndex` 与 `MatrixStore` 各自完整跑一遍检查（启动一次性开销，各约秒级）；
  如需优化可加进程内缓存，本轮不做。
