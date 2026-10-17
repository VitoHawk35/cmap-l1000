# task-C2 交付说明 · cmap 事件循环阻塞与部署

任务ID：C2（P1）
分支：`fix/C2-async-deploy`
基线提交：`8093b78`（origin/master，merge: C0 测试脚手架）

## 改动文件（文件:行号范围）

### 问题 1：async 接口内的同步 CPU 计算

- `app/api/search.py:58` — `/search` 改为同步 `def`（函数体内无 `await`）
- `app/api/wtcs_search.py:82` — `/search_wtcs` 改为同步 `def`
- `app/api/tau_search.py:198` — `/submit_tau` 改为同步 `def`
- `app/api/tau_search.py:225` — `/tau_job/{job_id}` 改为同步 `def`
- `app/api/tau_search.py:247` — `/search_tau` 改为同步 `def`
- `app/api/extract.py:37` — `/extract` 改为同步 `def`
- `app/api/export.py:80` — `/export` 改为同步 `def`
- `app/api/export_wtcs.py:72` — `/export_wtcs` 改为同步 `def`
- `app/api/export_data.py:76,97` — `/export_data`、`/export_data/{token}` 改为同步 `def`
- `app/api/csv_parser.py:287` — `/convert_to_ids` 改为同步 `def`（无 `await`）
- `app/api/csv_parser.py:98-244` — 新增同步 `_parse_csv_content()`；`parse_csv` 仍保留 `async def`（`await file.read()`），读取后调用 `await run_in_threadpool(_parse_csv_content, ...)`（`:246-284`）
- `app/api/wtcs_search.py:55-76` — 新增同步 `_process_wtcs_batch()`（原流式循环内的逐批打分+堆维护）；`:253-257` 用 `await run_in_threadpool(...)` 调用，SSE 生成器仍为 async

### 问题 2：部署 worker 与重启残留任务

- `start.sh:36` — `gunicorn -w 4` → `gunicorn -w 1 --threads 8`（`-k uvicorn.workers.UvicornWorker` 保留）
- `deploy/cmap.service:19-22` — 注释与 `ExecStart` 改为 `-w 1 --threads 8`
- `deploy/Dockerfile:26-27` — `CMD` 改为 `"-w", "1", "--threads", "8"`
- `deploy/DEPLOY_GUIDE.md:143,300-307` — 启动示例与调优说明同步为单 worker（避免文档与配置矛盾）
- `deploy/README.md:105-116` — 工作进程/内存说明同步
- `app/core/job_store.py:23,91-113` — 新增 `RESTART_ERROR_MESSAGE` 与 `fail_interrupted_jobs()`：把所有 `pending/running` 任务标为 `failed`，`error="服务重启，任务中断，请重新提交"`
- `app/main.py:66-71` — `@app.on_event("startup")` 调用 `fail_interrupted_jobs()`（兼容老版本 FastAPI）
- `app/api/tau_search.py:246` — `/search_tau` 增加 `deprecated=True`，接口仍保留

### 问题 3：CORS 与前端同源

- `app/main.py:31-51` — CORS 白名单改为环境变量 `CMAP_CORS_ORIGINS`（逗号分隔，自动去空白）；为空时不注册 `CORSMiddleware`
- `index.html:647` — `apiBaseUrl` 改为相对路径 `''`

### 依赖

- `requirements.txt:8` — 补 `scipy>=1.7.0`。依据：`app/core/post_processor.py:23` 直接 `from scipy import stats`；生产 `requirements-prod.txt` 已有 scipy，但按 `requirements.txt` 做本地/新环境安装时会缺依赖（C0 已把该决策留给 C2）。仅补一行，未改动其他依赖版本。

## 测试

新增 `tests/test_async_deploy.py`（7 个测试）：

1. `test_health_not_blocked_by_slow_search` — 用 `monkeypatch` 把 `CosineScorer.top_k_both` 打桩为 `time.sleep(2)`；一个线程发起 `/api/v1/search`，同时请求 `/health`，断言 `/health` < 200ms（两个请求共享同一 TestClient 事件循环，若接口仍是 async 会阻塞而失败）。
2. `test_interrupted_jobs_marked_failed_on_startup` — 手工写入 `running`/`pending` 任务文件，`with TestClient(app)` 触发 startup 重新创建应用，断言两者变为 `failed` 且错误文案正确。
3. `test_cpu_bound_endpoints_are_sync_functions` — 断言 11 个 CPU 密集接口为同步 `def`；`parse_csv` 与 SSE 流式接口仍为 async。
4. `test_search_tau_is_deprecated_in_openapi` — `/api/v1/search_tau` 在 OpenAPI 中 `deprecated: true`。
5. `test_wtcs_stream_still_returns_result` — 流式接口改用线程池后仍能正常产出 `result` 事件。
6. `test_parse_csv_runs_in_threadpool_and_still_works` — CSV 解析移入线程池后，上下调基因提取结果不变。
7. `test_cors_origins_from_env` — `CMAP_CORS_ORIGINS` 逗号分隔/空白/空值解析。

`pytest -q` 输出：

- Python 3.8.20（pydantic 2.10.6 / fastapi 0.124.4 / starlette 0.44.0）：

```
.............                                                            [100%]
13 passed, 2 warnings in 5.44s
```

- Python 3.11.7（pydantic 2.14.1 / fastapi 0.143.3 / starlette 1.8.0）：

```
.............                                                            [100%]
13 passed, 3 warnings in 6.16s
```

- Python 3.8 `py_compile app/*.py app/*/*.py tests/*.py` 全通过；新增代码只用 `typing` 兼容写法，无 PEP 585/604。
- pydantic 模型未改动；本任务未引入任何 pydantic v1/v2 差异写法（C0 已说明本机无法安装 pydantic v1，v2 两代版本均通过）。
- 完整输出：`D:\agent-workspace\deliveries\task-C2\pytest-py38.txt`、`pytest-py311.txt`。

## 验收逐条核对

- [x] 合成数据上将打分打桩慢 2 秒，同时请求 `/health`，`/health` 在 200ms 内返回（`test_health_not_blocked_by_slow_search`，实测断言 < 0.2s）
- [x] 手工写入 `running` 任务文件，重新创建 TestClient 触发 startup 后任务变为 `failed`，错误为「服务重启，任务中断，请重新提交」（`test_interrupted_jobs_marked_failed_on_startup`，同时覆盖 pending）
- [x] `grep -rn "\-w 4\|\"-w\", \"4\"" start.sh deploy/` 无命中（已实测输出 `NO_HITS`）

## 部署操作步骤（供人执行；本 agent 未重启生产服务）

前置：在 GitHub 审阅并合并 `fix/C2-async-deploy` 到 `master`。

1. 服务器拉取合并后的 master（只读红线下由人执行）：

```bash
cd ~/cmap
git fetch origin
git checkout master
git pull --ff-only origin master
```

2. 若生产使用 `start.sh`（任务文件所述方式）：

```bash
cd ~/cmap
./stop.sh     # 停旧进程（内部 pkill gunicorn.*8001）
./start.sh    # 新参数：gunicorn -w 1 --threads 8
./status.sh
```

3. 若生产使用 systemd `cmap.service`：

```bash
cd ~/cmap
sudo cp deploy/cmap.service /etc/systemd/system/cmap.service
sudo systemctl daemon-reload
sudo systemctl restart cmap
sudo systemctl status cmap --no-pager
```

4. 验证：

```bash
curl -fsS http://127.0.0.1:8001/health          # {"status":"healthy"}
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/   # 200
ps -ef | grep '[g]unicorn' | grep app.main:app  # 应为 1 个 master + 1 个 worker
```

5. 重启后确认：重启前处于 `pending/running` 的 Tau 任务在 `temp/jobs/*.json` 中应变为 `failed`，错误为「服务重启，任务中断，请重新提交」；重新提交即可。

6. CORS：同源部署无需任何配置（默认不注册 CORS 中间件）。若确有跨域前端，需在 `start.sh` 或 systemd 的 `Environment=` 中显式设置 `CMAP_CORS_ORIGINS=https://origin-a.example,https://origin-b.example`。

## 待人工确认（🧑‍⚖️）

- **D6**：gunicorn 参数由 `-w 4` 改为 `-w 1 --threads 8`（start.sh / deploy/cmap.service / deploy/Dockerfile 三处）。理由：memmap 不共享；Tau 任务跑在 worker 内部 daemon 线程，worker 回收会丢任务且状态永久 `running`。请确认可接受单 worker。
- **D2**：CORS 白名单改走环境变量 `CMAP_CORS_ORIGINS`（默认空 = 不启用）；前端 `apiBaseUrl` 固定相对路径 `''`（同源）。请确认无外部跨域入口仍依赖原 `allow_origins=["*"]` 或硬编码 `https://10.39.15.238:8001`。

## 发现但未处理

1. `app/api/csv_parser.py:313-335` 存在 `convert_to_ids` `return` 之后的**不可达死代码**（一个引用未定义 `gene_ids` 的“Entrez → Symbol”函数残留）。属范围外既有问题，未删除，建议后续清理。
2. `run.py:34` 仍为 uvicorn `workers=1`，与生产 gunicorn 参数一致，未改动。
3. `app/api/wtcs_search.py` 流式接口中 `query_vector` 变量未被使用（既有代码，保留未动）。
4. `--threads 8` 对 `UvicornWorker` 的实际线程池行为取决于 gunicorn/uvicorn 版本：同步接口实际由 AnyIO 线程池执行，`--threads` 主要对齐任务要求与运维预期；如需严格限制并发线程数，后续可评估 `anyio` 线程池上限。
