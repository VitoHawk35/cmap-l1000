#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C2：事件循环阻塞修复与部署参数回归测试"""

import inspect
import json
import os
import threading
import time


def _payload(synthetic_data):
    return {
        "up_genes": synthetic_data["up_gene_ids"],
        "down_genes": synthetic_data["down_gene_ids"],
    }


def test_health_not_blocked_by_slow_search(synthetic_data, monkeypatch):
    """打分被拖慢 2 秒时，/health 仍应在 200ms 内返回（证明未阻塞事件循环）"""
    from fastapi.testclient import TestClient

    from app.api import search as search_module
    from app.main import app

    # 预热单例，避免首次加载元数据/矩阵的时间计入测量
    base_scorer = search_module.get_scorer()
    search_module.get_metadata_index()
    search_module.get_matrix_store()
    search_module.get_gene_to_idx()

    class _SlowScorer:
        def top_k_both(self, *args, **kwargs):
            time.sleep(2.0)
            return base_scorer.top_k_both(*args, **kwargs)

    monkeypatch.setattr(search_module, "get_scorer", lambda: _SlowScorer())

    result = {}

    def _call_search():
        result["response"] = client.post(
            "/api/v1/search", json=_payload(synthetic_data)
        )

    # 使用 with 进入 TestClient，使两个请求共享同一个事件循环（否则测不出阻塞）
    with TestClient(app) as client:
        worker = threading.Thread(target=_call_search)
        worker.start()
        time.sleep(0.3)  # 确保 search 已进入 2 秒的打分打桩

        t0 = time.perf_counter()
        health = client.get("/health")
        elapsed = time.perf_counter() - t0

        worker.join(timeout=30)
        assert not worker.is_alive(), "search 请求未在 30 秒内结束"

    assert health.status_code == 200
    assert elapsed < 0.2, f"/health 被 search 阻塞：{elapsed:.3f}s"
    assert result["response"].status_code == 200, result["response"].text


def test_interrupted_jobs_marked_failed_on_startup(synthetic_data):
    """重启 app（触发 startup）后，遗留的 pending/running 任务应变为 failed"""
    from fastapi.testclient import TestClient

    from app.core import job_store
    from app.main import app

    os.makedirs(job_store.JOBS_DIR, exist_ok=True)
    jobs = {
        "c2-running-job": "running",
        "c2-pending-job": "pending",
    }
    for job_id, status in jobs.items():
        path = os.path.join(job_store.JOBS_DIR, f"{job_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "job_id": job_id,
                "status": status,
                "payload": {},
                "created_at": time.time(),
                "updated_at": time.time(),
                "progress": None,
                "result": None,
                "error": None,
            }, f)

    # 进入 with 触发 startup 事件（等价于重启 app）
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    for job_id in jobs:
        path = os.path.join(job_store.JOBS_DIR, f"{job_id}.json")
        with open(path, "r", encoding="utf-8") as f:
            job = json.load(f)
        assert job["status"] == "failed"
        assert job["error"] == job_store.RESTART_ERROR_MESSAGE


def test_cpu_bound_endpoints_are_sync_functions():
    """CPU 密集接口应为同步 def（FastAPI 自动放入线程池），流式/上传接口保留 async"""
    from app.api import csv_parser
    from app.api import export as export_module
    from app.api import export_data, export_wtcs, extract, search, tau_search, wtcs_search

    sync_endpoints = [
        search.search_reversals,
        wtcs_search.search_reversals_wtcs,
        tau_search.submit_tau,
        tau_search.get_tau_job,
        tau_search.search_tau,
        extract.extract_features,
        export_module.export_results,
        export_wtcs.export_results_wtcs,
        export_data.export_data,
        export_data.download_export,
        csv_parser.convert_to_ids,
    ]
    for endpoint in sync_endpoints:
        assert not inspect.iscoroutinefunction(endpoint), endpoint.__name__

    # 含 await file.read() / SSE 生成器，必须保留 async
    assert inspect.iscoroutinefunction(csv_parser.parse_csv)
    assert inspect.iscoroutinefunction(wtcs_search.search_reversals_wtcs_stream)


def test_search_tau_is_deprecated_in_openapi(client):
    """同步 /search_tau 保留但标记 deprecated"""
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/search_tau"]["post"].get("deprecated") is True


def test_wtcs_stream_still_returns_result(client, synthetic_data):
    """流式接口改用线程池后仍能正常产出结果事件"""
    with client.stream(
        "POST", "/api/v1/search_wtcs_stream", json=_payload(synthetic_data)
    ) as resp:
        body = "".join(resp.iter_text())

    assert resp.status_code == 200
    assert '"type": "result"' in body


def test_parse_csv_runs_in_threadpool_and_still_works(client, synthetic_data):
    """CSV 解析改为线程池执行后行为不变"""
    content = "gene,logFC,PValue\nGENE10001,2.0,0.01\nGENE10002,-2.0,0.01\n"
    resp = client.post(
        "/api/v1/parse_csv",
        files={"file": ("diff.csv", content.encode("utf-8"), "text/csv")},
        data={"pvalue_threshold": "0.05", "top_n": "50"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["up_genes"] == [10001]
    assert data["down_genes"] == [10002]


def test_cors_origins_from_env(monkeypatch):
    """CMAP_CORS_ORIGINS 逗号分隔解析，空白/空值忽略"""
    from app.main import _cors_origins_from_env

    monkeypatch.setenv(
        "CMAP_CORS_ORIGINS", " https://a.example , https://b.example ,"
    )
    assert _cors_origins_from_env() == [
        "https://a.example", "https://b.example"
    ]

    monkeypatch.setenv("CMAP_CORS_ORIGINS", "")
    assert _cors_origins_from_env() == []
