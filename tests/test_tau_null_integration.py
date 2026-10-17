#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C3 集成测试：Tau 搜索结果左连接随机签名 null 的 p 值 / FDR。

验收：
1. /submit_tau 结果里埋入的逆转药 fdr < 0.05；
2. 同一套字段也出现在同步 /search_tau；
3. 删除药物矩阵后 /submit_tau 仍成功且 null_calibration == "unavailable"。
"""

import os
import time

import pytest


def _payload(synthetic_data, **extra):
    payload = {
        "up_genes": synthetic_data["up_gene_ids"],
        "down_genes": synthetic_data["down_gene_ids"],
        "top_k": 20,
        "bottom_k": 20,
    }
    payload.update(extra)
    return payload


def _run_tau(client, payload, timeout=180):
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


def _find_result(result, drug_name):
    for key in ("top_results", "bottom_results"):
        for item in result.get(key, []):
            if item["pert_iname"] == drug_name:
                return item
    return None


def test_submit_tau_joins_fdr(client, synthetic_data, drug_median_data):
    """异步 /submit_tau：逆转药 fdr < 0.05，且所有结果带 null 字段。"""
    result = _run_tau(client, _payload(synthetic_data))

    assert result["null_calibration"] == "ok"
    item = _find_result(result, synthetic_data["reversal_drug"])
    assert item is not None, "逆转药不在 top/bottom 结果中"
    assert item["fdr"] is not None
    assert item["p_value"] is not None
    assert item["null_z"] is not None
    assert item["fdr"] < 0.05, "逆转药 fdr={}".format(item["fdr"])
    # 完美逆转药应比随机更逆转（null_z 负）
    assert item["null_z"] < 0

    for key in ("top_results", "bottom_results"):
        for row in result[key]:
            assert "p_value" in row and "fdr" in row and "null_z" in row


def test_sync_search_tau_joins_fdr(client, synthetic_data, drug_median_data):
    """同步 /search_tau：同样左连接 null 字段。"""
    resp = client.post(
        "/api/v1/search_tau", json=_payload(synthetic_data, top_k=20, bottom_k=20)
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()

    assert result["null_calibration"] == "ok"
    item = _find_result(result, synthetic_data["reversal_drug"])
    assert item is not None
    assert item["fdr"] is not None and item["fdr"] < 0.05
    assert item["p_value"] is not None
    assert item["null_z"] is not None


def test_insufficient_landmark_genes_status(
    client, synthetic_data, drug_median_data
):
    """up+down 的 landmark 基因 < 10 时返回 insufficient_landmark_genes。"""
    payload = _payload(
        synthetic_data,
        up_genes=synthetic_data["up_gene_ids"][:5],
        down_genes=synthetic_data["down_gene_ids"][:4],
    )
    result = _run_tau(client, payload)

    assert result["null_calibration"] == "insufficient_landmark_genes"
    for key in ("top_results", "bottom_results"):
        for row in result[key]:
            assert row["p_value"] is None
            assert row["fdr"] is None
            assert row["null_z"] is None


def test_missing_matrix_marks_unavailable(
    client, synthetic_data, drug_median_data, tmp_path, monkeypatch
):
    """删除药物矩阵后 Tau 搜索仍成功，null_calibration == "unavailable"。"""
    from app.scoring import null_calibrator as nc
    from scripts.build_drug_median import build_drug_median

    matrix_path = drug_median_data["matrix_path"]
    assert os.path.exists(matrix_path)

    nc.reset_null_calibrator()

    removed = False
    try:
        os.remove(matrix_path)
        removed = True
    except OSError:
        # Windows 上 mmap 句柄偶发未释放时的退路：把路径指向不存在的文件，
        # 等价于矩阵缺失。
        monkeypatch.setattr(
            nc, "DRUG_MEDIAN_MATRIX_PATH", str(tmp_path / "missing.npy")
        )

    try:
        assert nc.get_null_calibrator() is None
        result = _run_tau(client, _payload(synthetic_data))

        assert result["null_calibration"] == "unavailable"
        for key in ("top_results", "bottom_results"):
            for row in result[key]:
                assert row["p_value"] is None
                assert row["fdr"] is None
                assert row["null_z"] is None
    finally:
        if removed:
            # 恢复矩阵，供后续测试使用
            build_drug_median(synthetic_data["data_dir"])
        nc.reset_null_calibrator()
