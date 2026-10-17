# task-C0 交付说明 · cmap 测试脚手架

任务ID：C0（cmap 测试脚手架，P0）
分支：fix/C0-test-scaffold
基线提交：aa79530（origin/master，"sync: 服务器最新代码同步"）

## 改动文件（文件:行号范围）

- `app/config.py:14` — `DATA_DIR` 改为 `os.getenv("CMAP_DATA_DIR", <原默认值>)`
- `app/config.py:28` — `TOUCHSTONE_DIR` 改为 `os.getenv("CMAP_TOUCHSTONE_DIR", <原默认值>)`
- `app/config.py:33-38` — `N_GENES`/`N_SIGS` 改为 `int(os.getenv("CMAP_N_GENES", "12328"))` / `"473647"`；新增 `TEMP_DIR = os.getenv("CMAP_TEMP_DIR", os.path.join(PROJECT_ROOT, "temp"))`
- `app/core/job_store.py:14-16` — `JOBS_DIR` 改为基于 `config.TEMP_DIR`（原硬编码 `temp/jobs`，默认值不变）
- `app/core/export_store.py:14-16` — `EXPORT_DIR` 同上（原硬编码 `temp/exports`）
- `tests/make_synthetic_data.py`（新增）— 合成数据生成器，可独立运行（CLI）
- `tests/conftest.py`（新增）— session fixture：生成数据到 tmp 目录，**在 import app 之前**设置 `CMAP_DATA_DIR/CMAP_N_GENES/CMAP_N_SIGS/CMAP_TEMP_DIR`；提供 `TestClient`
- `tests/test_health.py`（新增）— `/health` 200、`/` 前端托管冒烟
- `tests/test_search.py`（新增）— `/api/v1/search`、`/api/v1/search_wtcs`、`/api/v1/submit_tau`+轮询 `/api/v1/tau_job/{id}` 三接口 top1 断言
- `tests/test_config_defaults.py`（新增）— 子进程清空 CMAP_* 后 import config，逐值比对默认值与改动前一致
- `requirements-dev.txt`（新增）— pytest / httpx / scipy

未改动：`metadata_index.py:73-74` 的列数校验保留（校验对象 `N_SIGS` 本身已可被环境变量覆盖，无需改该行）。

## 合成数据集设计（关键说明）

- 规模：N_GENES=200、N_SIGS=3000（60 药物 × 5 细胞系 × 10 剂量），40 个 `is_touchstone=1`。
- 矩阵为**裸 float32 memmap**（`np.memmap(path, 'float32', 'w+', shape=...)` 写入，无 .npy 头），与 `matrix_store.py:43-48` 读取方式一致。
- 埋入逆转药 `reversib`：所有签名 up 基因 z=−3、down 基因 z=+3，WTCS 饱和到 −1.0。
- 两处相对任务"建议规模"的**有意偏离**（为使"三接口 top1=逆转药"确定成立）：
  1. **剂量重复相关**：同一 (药物,细胞系) 的 10 个剂量共享 base 向量 + 0.1σ 噪声（仿真实 LINCS 重复高相关）。纯独立噪声下随机排序的 WTCS 极值会让某个 touchstone 药在药物级 max|ncs| 聚合后盖过逆转药（实测 drug-059 ncs=−1.6 vs reversib −3.1 时 Tau 并列翻车）。
  2. **reversib 属于 touchstone**：Tau 公式 `-mean(x<=neg_ref)*100` 使 neg_ref 最小值恒取 −100；若 reversib 不在参考集内，会与最负 touchstone 药并列 −100，名次取决于不稳定排序。作为参考集内最负成员则**唯一**取得 −100（其余严格 > −100），三接口 top1 确定。
- 符号约定：WTCS/Tau 负=逆转，top_results 最负在前（与任务文件统一约定一致，未改动任何打分代码）。

## 测试

新增 6 个测试（health×2、search×3、config 默认值×1）。本机无 Python 3.8 解释器之外还需完整依赖，故建了两个 venv（`D:\agent-workspace\venvs\cmap-c0-311\`、 `cmap-c0-38\`，不入 git）：

- **Python 3.11.7**（pydantic 2.14.1 / fastapi 0.143.3 / pandas 3.0.6 / numpy 2.4.6 / scipy 1.17.1 / pytest 9.1.1 / httpx 0.28.1）：

```
$ python -m pytest tests -q
......                                                                   [100%]
6 passed, 1 warning in 2.19s
```

- **Python 3.8.20**（pydantic 2.10.6 / fastapi 0.124.4 / pandas 2.0.3 / numpy 1.24.4 / scipy 1.10.1 / pytest 8.3.5 / httpx 0.28.1）：

```
$ python -m pytest tests -q
......                                                                   [100%]
6 passed in 1.89s
```

- 另做 `python3.8 -m py_compile app/*.py app/*/*.py tests/*.py` 全通过；新增代码只用 `typing.List/Dict`，无 PEP 585/604 语法。pydantic v2 两代版本（2.10/2.14）+ pandas 2/3 双组合均通过（本环境无法装 pydantic v1，schemas 未改动、无 v1 不兼容写法）。
- 完整输出：`D:\agent-workspace\deliveries\task-C0\pytest-py311.txt`、`pytest-py38.txt`。

## 验收逐条核对

- [x] `pytest -q` 在 Python 3.8 和 3.11 下都通过（真实双解释器跑通，非仅语法检查；输出见上）
- [x] `GET /health` 返回 200（test_health）；对埋入的逆转药 reversib：`/api/v1/search` top1=reversib（score<0）、`/api/v1/search_wtcs` top1=reversib（score<0）、`/api/v1/submit_tau`→轮询至 completed 后 top1=reversib（tau=−100）（test_search 三条断言）
- [x] 不设环境变量时所有路径与原来完全一致（test_config_defaults 子进程逐值断言：DATA_DIR/各文件路径/TOUCHSTONE_DIR/N_GENES=12328/N_SIGS=473647/TEMP_DIR=项目根/temp；job_store→temp/jobs、export_store→temp/exports 默认值不变）

## 待人工确认（🧑‍⚖️）

无。（合成数据的两处偏离属于测试基建内部决策，不影响生产代码行为。）

## 发现但未处理

1. **Tau 饱和并列（真实数据同样存在）**：`_calculate_tau` 中 `tau=-100` 会在「比所有负 touchstone 更负的药」与「最负的 touchstone 药」之间并列，最终名次依赖 `nsmallest`/`sort_values`（quicksort，不稳定）的 tie 顺序。建议后续任务（C1/C3）考虑同分时按 summary_ncs 二次排序。
2. `requirements.txt` 缺 scipy 但 `post_processor.py:23` 直接 `from scipy import stats`——生产靠 requirements-prod.txt 兜底，已在 requirements-dev.txt 补上；是否把 scipy 并入主 requirements.txt 留给 C2（部署）决定。
3. 本机 pip 走清华镜像直连被重置（10053），7897 代理已失效；改用阿里云镜像直连成功。git push 按 README 直连。
