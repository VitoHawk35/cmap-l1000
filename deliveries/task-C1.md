# task-C1 交付说明 · cmap "150" 修复

任务ID：C1（cmap "150" 修复，P0）
分支：`fix/C1-topk-150`
基线提交：`8093b78`（origin/master，`merge: C0 测试脚手架`，含 C0）

## 改动文件（文件:行号范围）

| 文件 | 行号 | 改动 |
|---|---|---|
| `app/models/schemas.py` | 8, 10 | `from pydantic import BaseModel, Field`；`from ..config import DEFAULT_TOP_K` |
| `app/models/schemas.py` | 37 | `SearchRequest.top_k = Field(DEFAULT_TOP_K, ge=1, le=5000)`（v1/v2 双兼容写法） |
| `app/models/schemas.py` | 66-67 | `TauSearchRequest.top_k/bottom_k = Field(DEFAULT_TOP_K, ge=1, le=5000)` |
| `app/api/tau_search.py` | 28, 87-88 | 导入 `DEFAULT_TOP_K`；异步任务默认值 `payload.get(..., DEFAULT_TOP_K)` |
| `app/core/post_processor.py` | 25, 85-86 | 导入 `DEFAULT_TOP_K`；`process()` 两个 k 参数默认值改为 `DEFAULT_TOP_K` |
| `app/core/post_processor.py` | 123-124 | bottom 结果按 `ascending=False` 组装（最正在前）；top 仍升序 |
| `app/core/post_processor.py` | 329-351 | `_to_results()` 新增 `ascending` 参数；排序改 `kind='mergesort'`（稳定排序，±100 并列可复现） |
| `app/api/csv_parser.py` | 119-121 | 服务端校验 `10 <= top_n <= 150`，否则 422 |
| `index.html` | 321 | CSV 导入 Top N 输入框 `max="500"` → `max="150"` |
| `index.html` | 690-696 | `currentSearchResults` bottom 分支：去掉无条件 `reverse()`，改为 `b.score - a.score` 降序后重排名次 |
| `index.html` | 766-771 | 新增 `methods.clampTopK(v)`（10..5000，非法值回退 50） |
| `index.html` | 929 | cosine `/api/v1/search` 请求体 `top_k: this.clampTopK(this.searchForm.topK)` |
| `index.html` | 948 | WTCS 流式 `/api/v1/search_wtcs_stream` 请求体同样包 `clampTopK` |
| `index.html` | 1058-1059 | Tau `submit_tau` 请求体 `top_k/bottom_k` 改为 `this.clampTopK(this.searchForm.topK)`（删除写死的 150） |
| `tests/test_topk.py` | 新增 | 8 个 C1 专项测试（见下） |

### 关于 bottom 排序的额外必要改动

任务原文第 4 条的前提是“后端 bottom 已按降序返回”。核实发现 `post_processor._to_results()` 对 top/bottom **都**做升序排序，导致 Tau 的 `bottom_results` 实际是“最弱在前”，与验收第 2 条（三种算法 bottom 分数单调不增）及统一符号约定相矛盾。因此给 `_to_results()` 增加 `ascending` 参数，bottom 传 `False`。这是验收直接要求的最小改动，未触及打分公式或其它逻辑。

同时按 C0 遗留提示，把 `sort_values` 改为稳定排序 `kind='mergesort'`，使 ±100 饱和并列时的名次可复现（不改变分数与集合，仅固定 tie 顺序）。

## 测试

新增 `tests/test_topk.py`：

1. `test_tau_default_k_is_default_top_k` — 不传 top_k/bottom_k → 各 50 条（`DEFAULT_TOP_K`）
2. `test_tau_top_k_20` — 传 20 → 两个方向各 20 条
3. `test_tau_top_k_out_of_range_422[0]` / `[10000]` — top_k 与 bottom_k 越界均 422
4. `test_bottom_results_desc_cosine` — `/api/v1/search` bottom 分数单调不增
5. `test_bottom_results_desc_wtcs` — `/api/v1/search_wtcs` bottom 分数单调不增
6. `test_bottom_results_desc_tau` — `/api/v1/submit_tau` bottom 的 `tau_score` 单调不增
7. `test_parse_csv_top_n_range` — top_n=9/151 → 422，150 → 200

`pytest -q`（Python 3.8.20 venv，`D:\agent-workspace\venvs\cmap-c0-38`）：

```
..............                                                           [100%]
14 passed in 3.59s
```

`pytest -q`（Python 3.11.7 venv，`D:\agent-workspace\venvs\cmap-c0-311`）：

```
..............                                                           [100%]
14 passed, 1 warning in 4.73s
```

- `python3.8 -m py_compile app/models/schemas.py app/api/tau_search.py app/core/post_processor.py app/api/csv_parser.py tests/test_topk.py` → 通过（无 PEP 585/604 语法）。
- pydantic v1.10.12（系统环境）直接实例化校验：`SearchRequest` 默认 50，`TauSearchRequest` 默认 50/50，0 与 10000 均抛 `ValidationError`（即 HTTP 422），v1/v2 双兼容成立。
- 完整输出：`D:\agent-workspace\deliveries\task-C1\pytest-py38.txt`、`pytest-py311.txt`、`compat-and-grep.txt`、`frontend-check.txt`。

## 验收逐条核对

- [x] `POST /api/v1/submit_tau` 不传 top_k → `top_results` 长度 = 50；传 `top_k=20` → 20；传 `top_k=0` 或 `10000` → 422（`tests/test_topk.py` 前 3 组；bottom_k 同样校验）。
- [x] 三种算法（cosine / WTCS / Tau）返回的 bottom 结果分数均单调不增（`test_bottom_results_desc_*` 三条；Tau 使用 `tau_score`）。
- [x] 前端核对（node 脚本 `D:\agent-workspace\deliveries\task-C1\verify_frontend.js`，输出见 `frontend-check.txt`）：
  - `performSearchTau` 函数体不含 `150`；
  - Tau 请求体 `top_k/bottom_k` 均为 `this.clampTopK(this.searchForm.topK)`；
  - cosine 与 WTCS 流式请求体均包 `clampTopK`；
  - `clampTopK` 实现为 `parseInt` + `Math.min(5000, Math.max(10, n))`，非法值回退 50；模拟结果：20→20、0→10、99999→5000、`"abc"`→50；
  - bottom 视图改为 `b.score - a.score` 降序、不再 `reverse()`；
  - CSV Top N 输入框 `max="150"`，全文件无 `max="500"`。
  - 说明：本地无生产数据/运行中的后端，未做真实浏览器点击；结果条数由后端测试（20→20、默认→50）与上述静态断言共同覆盖。
- [x] `grep -rn --exclude-dir=__pycache__ "150" app run.py index.html` 剩余命中：
  ```
  app/api/csv_parser.py:119:    # 服务端校验：top_n 与前端输入框保持一致（10-150）
  app/api/csv_parser.py:120:    if not 10 <= top_n <= 150:
  app/api/csv_parser.py:121:        raise HTTPException(status_code=422, detail="top_n 必须在 10 到 150 之间")
  index.html:321:                                            max="150"
  ```
  全部为 D7 的 CSV 导入 topN 上限 150（本轮按要求改为 150 后新增/修改的行），**已无与 `top_k/bottom_k` 相关的 150 命中**。

## 待人工确认（🧑‍⚖️）

- **D7：CSV 导入 topN 上限已按任务默认建议从 500 改为 150**（前端输入框 `max=150` + 服务端 `10..150` 校验，越界返回 422）。这与 CLUE 规范一致，但属于用户可见行为变化，请确认是否接受；如需保留 500，只需改回 `index.html:321` 的 `max` 与 `csv_parser.py:120` 的上界。

## 发现但未处理

1. **±100 饱和并列**：Tau 分数在参考分布端点会大量并列（C0 已记录）。本次仅将排序改为稳定排序以保证可复现，未按 `summary_ncs` 做二次排序（超出本任务范围；建议 C3/C5 统一处理）。
2. `app/api/csv_parser.py` 末尾 `convert_to_ids` 的 `return` 之后有一段不可达的重复代码（历史遗留，`gene_ids` 未定义），本次未改动。
3. `README.md` §2 仍写着“代理 7897 已停用、直连可用”，与本次实测（直连 GitHub 443 超时、必须走 7897）不符；本次未改 README（非本任务范围），已按任务指令用代理完成 fetch/push。
