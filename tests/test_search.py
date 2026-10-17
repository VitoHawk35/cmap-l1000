#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
核心搜索接口测试：埋入的逆转药 reversib 必须在三个接口的 top 第 1 名

符号约定（见任务文件）：WTCS / Tau 负 = 逆转，top_results 最负在前。
"""

import time


def _query_payload(synthetic_data):
    return {
        "up_genes": synthetic_data["up_gene_ids"],
        "down_genes": synthetic_data["down_gene_ids"],
    }


def test_search_top1_is_reversal_drug(client, synthetic_data):
    """GET /api/v1/search（余弦相似度）：top 第 1 名是埋入的逆转药"""
    resp = client.post("/api/v1/search", json=_query_payload(synthetic_data))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["query_up_count"] == len(synthetic_data["up_gene_ids"])
    assert len(data["top_results"]) > 0
    top1 = data["top_results"][0]
    assert top1["rank"] == 1
    assert top1["drug"] == synthetic_data["reversal_drug"]
    assert top1["score"] < 0  # 负 = 逆转


def test_search_wtcs_top1_is_reversal_drug(client, synthetic_data):
    """POST /api/v1/search_wtcs（WTCS 算法）：top 第 1 名是埋入的逆转药"""
    resp = client.post("/api/v1/search_wtcs", json=_query_payload(synthetic_data))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["top_results"]) > 0
    top1 = data["top_results"][0]
    assert top1["rank"] == 1
    assert top1["drug"] == synthetic_data["reversal_drug"]
    assert top1["score"] < 0


def test_submit_tau_job_top1_is_reversal_drug(client, synthetic_data):
    """POST /api/v1/submit_tau + 轮询 /api/v1/tau_job/{id}：top 第 1 名是逆转药"""
    resp = client.post("/api/v1/submit_tau", json=_query_payload(synthetic_data))
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # 轮询直到完成（合成数据很小，正常几秒内完成）
    deadline = time.time() + 120
    job = None
    while time.time() < deadline:
        resp = client.get(f"/api/v1/tau_job/{job_id}")
        assert resp.status_code == 200, resp.text
        job = resp.json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert job is not None and job["status"] == "completed", f"任务未完成: {job}"
    result = job["result"]
    assert result is not None
    assert len(result["top_results"]) > 0
    top1 = result["top_results"][0]
    assert top1["rank"] == 1
    assert top1["pert_iname"] == synthetic_data["reversal_drug"]
    assert top1["tau_score"] < 0  # 负 = 逆转
