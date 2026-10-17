#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C1 "150" 修复专项测试

覆盖：
1. Tau 接口不传 top_k/bottom_k 时使用 DEFAULT_TOP_K（50）
2. Tau 接口 top_k=20 时两个方向各返回 20 条
3. top_k/bottom_k 越界（0、10000）返回 422
4. 三种算法 bottom_results 的 score 单调不增（后端已按最正在前返回）
5. CSV 导入 top_n 服务端校验 10..150
"""

import time

import pytest


def _payload(synthetic_data, **extra):
    payload = {
        "up_genes": synthetic_data["up_gene_ids"],
        "down_genes": synthetic_data["down_gene_ids"],
    }
    payload.update(extra)
    return payload


def _run_tau(client, payload, timeout=120):
    """提交 Tau 异步任务并轮询到完成，返回 result。"""
    resp = client.post("/api/v1/submit_tau", json=payload)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        resp = client.get("/api/v1/tau_job/{}".format(job_id))
        assert resp.status_code == 200, resp.text
        job = resp.json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)

    assert job is not None and job["status"] == "completed", "任务未完成: {}".format(job)
    assert job["result"] is not None
    return job["result"]


def _assert_desc(scores, label):
    """断言分数单调不增（允许并列）。"""
    assert scores == sorted(scores, reverse=True), \
        "{} bottom 分数应单调不增: {}".format(label, scores)


def test_tau_default_k_is_default_top_k(client, synthetic_data):
    """不传 top_k/bottom_k → 各返回 DEFAULT_TOP_K（50）条。"""
    from app.config import DEFAULT_TOP_K

    assert DEFAULT_TOP_K == 50  # 与输入框默认值一致
    result = _run_tau(client, _payload(synthetic_data))
    assert len(result["top_results"]) == DEFAULT_TOP_K
    assert len(result["bottom_results"]) == DEFAULT_TOP_K


def test_tau_top_k_20(client, synthetic_data):
    """传 top_k=20 → 两个方向各 20 条。"""
    result = _run_tau(client, _payload(synthetic_data, top_k=20, bottom_k=20))
    assert len(result["top_results"]) == 20
    assert len(result["bottom_results"]) == 20


@pytest.mark.parametrize("bad_k", [0, 10000])
def test_tau_top_k_out_of_range_422(client, synthetic_data, bad_k):
    """top_k/bottom_k 越界 → 422（请求体校验，任务不会入队）。"""
    for field in ("top_k", "bottom_k"):
        resp = client.post(
            "/api/v1/submit_tau",
            json=_payload(synthetic_data, **{field: bad_k})
        )
        assert resp.status_code == 422, "{}={} 应返回 422: {}".format(
            field, bad_k, resp.text)


def test_bottom_results_desc_cosine(client, synthetic_data):
    """余弦 /search：bottom_results 分数单调不增。"""
    resp = client.post("/api/v1/search", json=_payload(synthetic_data, top_k=20))
    assert resp.status_code == 200, resp.text
    bottom = resp.json()["bottom_results"]
    assert len(bottom) == 20
    _assert_desc([r["score"] for r in bottom], "cosine")


def test_bottom_results_desc_wtcs(client, synthetic_data):
    """WTCS /search_wtcs：bottom_results 分数单调不增。"""
    resp = client.post("/api/v1/search_wtcs", json=_payload(synthetic_data, top_k=20))
    assert resp.status_code == 200, resp.text
    bottom = resp.json()["bottom_results"]
    assert len(bottom) == 20
    _assert_desc([r["score"] for r in bottom], "wtcs")


def test_bottom_results_desc_tau(client, synthetic_data):
    """Tau /submit_tau：bottom_results 的 tau_score 单调不增。"""
    result = _run_tau(client, _payload(synthetic_data, top_k=20, bottom_k=20))
    bottom = result["bottom_results"]
    assert len(bottom) == 20
    _assert_desc([r["tau_score"] for r in bottom], "tau")


def test_parse_csv_top_n_range(client):
    """CSV 导入 top_n 服务端校验：9/151 → 422，150 → 200。"""
    content = (
        "gene,logFC,PValue\n"
        "GENE10001,1.0,0.01\n"
        "GENE10002,-1.0,0.01\n"
    ).encode("utf-8")

    for bad in (9, 151):
        resp = client.post(
            "/api/v1/parse_csv",
            files={"file": ("diff.csv", content, "text/csv")},
            data={"top_n": str(bad)}
        )
        assert resp.status_code == 422, "top_n={} 应返回 422: {}".format(
            bad, resp.text)

    resp = client.post(
        "/api/v1/parse_csv",
        files={"file": ("diff.csv", content, "text/csv")},
        data={"top_n": "150"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["up_genes"] == [10001]
