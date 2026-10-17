#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tau分数搜索接口（完整CMAP后处理流程）

面向医疗人员的Perturbagen-level搜索结果
实现NCS归一化 -> 药物级聚合 -> Tau分数计算的全流程

v2: 增加异步任务支持，解决长时间计算导致的超时和页面关闭问题
"""

import uuid
import threading
import numpy as np
from fastapi import APIRouter, HTTPException
from typing import List
import time

from ..models.schemas import (
    TauSearchRequest, TauSearchResponse, TauSearchResult,
    TauJobSubmitResponse, TauJobStatusResponse
)
from ..core.metadata_index import MetadataIndex
from ..core.matrix_store import MatrixStore
from ..core.post_processor import CMAPPostProcessor
from ..core.job_store import create_job, get_job, update_job
from ..scoring.wtcs_scorer import WTCSScorer
from ..config import N_GENES, N_SIGS, ROW_NAMES_PATH
import pandas as pd

router = APIRouter()

# 单例实例
_metadata_index = None
_matrix_store = None
_gene_to_idx = None
_post_processor = None


def get_metadata_index() -> MetadataIndex:
    global _metadata_index
    if _metadata_index is None:
        _metadata_index = MetadataIndex()
    return _metadata_index


def get_matrix_store() -> MatrixStore:
    global _matrix_store
    if _matrix_store is None:
        _matrix_store = MatrixStore()
    return _matrix_store


def get_gene_to_idx() -> dict:
    """获取基因 ID 到行索引的映射"""
    global _gene_to_idx
    if _gene_to_idx is None:
        row_df = pd.read_csv(ROW_NAMES_PATH)
        gene_ids = row_df['gene_id'].astype(str).tolist()
        _gene_to_idx = {gene_id: idx for idx, gene_id in enumerate(gene_ids)}
    return _gene_to_idx


def get_post_processor() -> CMAPPostProcessor:
    """获取后处理器实例（启动时预加载）"""
    global _post_processor
    if _post_processor is None:
        _post_processor = CMAPPostProcessor()
    return _post_processor


def _run_tau_job(job_id: str, payload: dict):
    """
    后台线程执行的实际计算逻辑
    """
    print(f"\n[Job {job_id}] 后台任务启动 - {time.strftime('%H:%M:%S')}")
    update_job(job_id, status="running")

    try:
        metadata_index = get_metadata_index()
        matrix_store = get_matrix_store()
        gene_to_idx = get_gene_to_idx()
        post_processor = get_post_processor()

        up_genes = payload["up_genes"]
        down_genes = payload["down_genes"]
        top_k = min(payload.get("top_k", 150), N_SIGS // 2)
        bottom_k = min(payload.get("bottom_k", 150), N_SIGS // 2)

        # 1. 基因ID映射
        up_indices = []
        down_indices = []
        for gene_id in up_genes:
            gene_id_str = str(gene_id)
            if gene_id_str in gene_to_idx:
                up_indices.append(gene_to_idx[gene_id_str])
        for gene_id in down_genes:
            gene_id_str = str(gene_id)
            if gene_id_str in gene_to_idx:
                down_indices.append(gene_to_idx[gene_id_str])

        if len(up_indices) == 0:
            raise ValueError(f"上调基因数量不足（上调:{len(up_indices)}, 下调:{len(down_indices)}），请检查基因ID")

        # 2. 初始化 WTCS 打分器
        scorer = WTCSScorer(up_indices, down_indices)

        # 3. 批量计算全库WTCS分数
        batch_iterator = matrix_store.get_batch_iterator(batch_size=5000)
        query_vector = np.zeros(N_GENES, dtype=np.float32)

        all_indices = []
        all_scores = []
        batch_count = 0
        total_batches = (N_SIGS + 5000 - 1) // 5000

        for start_idx, end_idx, data in batch_iterator:
            batch_scores = scorer.score(query_vector, data)
            for i, score in enumerate(batch_scores):
                all_indices.append(start_idx + i)
                all_scores.append(float(score))

            batch_count += 1
            if batch_count % 10 == 0 or batch_count == total_batches:
                progress = {
                    "batch": batch_count,
                    "total_batches": total_batches,
                    "percent": round(batch_count / total_batches * 100, 1),
                    "stage": "scoring"
                }
                update_job(job_id, progress=progress)
                print(f"[Job {job_id}] Progress: {batch_count}/{total_batches} ({progress['percent']}%)")

        # 4. 后处理
        update_job(job_id, progress={"stage": "post_processing", "percent": 95})
        idx_to_sig = {v: k for k, v in metadata_index._sig_to_idx.items()}
        all_sig_ids = [idx_to_sig.get(idx, f"unknown_{idx}") for idx in all_indices]

        top_results, bottom_results = post_processor.process(
            sig_ids=all_sig_ids,
            scores=all_scores,
            return_top_k=top_k,
            return_bottom_k=bottom_k
        )

        # 5. 组装结果（用 dict 以便 json 序列化）
        top_response = [
            {
                "rank": r.rank,
                "pert_iname": r.pert_iname,
                "pert_type": r.pert_type,
                "tau_score": r.tau_score,
                "summary_ncs": r.summary_ncs,
                "best_wtcs": r.best_wtcs,
                "cell_count": r.cell_count,
                "best_cell_id": r.best_cell_id,
                "best_dose": r.best_dose,
                "is_touchstone": r.is_touchstone,
            }
            for r in top_results
        ]

        bottom_response = [
            {
                "rank": r.rank,
                "pert_iname": r.pert_iname,
                "pert_type": r.pert_type,
                "tau_score": r.tau_score,
                "summary_ncs": r.summary_ncs,
                "best_wtcs": r.best_wtcs,
                "cell_count": r.cell_count,
                "best_cell_id": r.best_cell_id,
                "best_dose": r.best_dose,
                "is_touchstone": r.is_touchstone,
            }
            for r in bottom_results
        ]

        result = {
            "query_up_count": len(up_indices),
            "query_down_count": len(down_indices),
            "top_results": top_response,
            "bottom_results": bottom_response,
        }

        update_job(job_id, status="completed", result=result, progress={"stage": "done", "percent": 100})
        print(f"[Job {job_id}] 任务完成 - {time.strftime('%H:%M:%S')}")

    except Exception as e:
        error_msg = str(e)
        update_job(job_id, status="failed", error=error_msg)
        print(f"[Job {job_id}] 任务失败: {error_msg}")


# ==================== 异步任务接口 ====================

@router.post("/submit_tau", response_model=TauJobSubmitResponse)
def submit_tau(request: TauSearchRequest):
    """
    提交 Tau 搜索异步任务
    立即返回 job_id，后台执行计算
    """
    job_id = str(uuid.uuid4())
    payload = {
        "up_genes": request.up_genes,
        "down_genes": request.down_genes,
        "top_k": request.top_k,
        "bottom_k": request.bottom_k,
    }
    create_job(job_id, payload)

    # 启动后台线程
    thread = threading.Thread(target=_run_tau_job, args=(job_id, payload), daemon=True)
    thread.start()

    print(f"[Submit] 任务 {job_id} 已提交")
    return TauJobSubmitResponse(
        job_id=job_id,
        status="pending",
        message="任务已提交，请通过 /tau_job/{job_id} 轮询状态"
    )


@router.get("/tau_job/{job_id}", response_model=TauJobStatusResponse)
def get_tau_job(job_id: str):
    """
    查询 Tau 异步任务状态与结果
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    return TauJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        progress=job.get("progress"),
        result=job.get("result"),
        error=job.get("error"),
    )


# ==================== 兼容旧接口（保留，但建议前端迁移到异步） ====================

@router.post("/search_tau", response_model=TauSearchResponse, deprecated=True)
def search_tau(request: TauSearchRequest):
    """
    Tau分数搜索（完整CMAP后处理流程）—— 同步版本，保留兼容
    计算时间较长（10-15分钟），建议前端使用 /submit_tau + /tau_job 异步接口
    """
    print(f"\n{'='*60}")
    print(f"[Tau Search] 开始处理请求 - {time.strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    metadata_index = get_metadata_index()
    matrix_store = get_matrix_store()
    gene_to_idx = get_gene_to_idx()
    post_processor = get_post_processor()

    # 防御：top_k和bottom_k不能超过总数的一半
    max_k = N_SIGS // 2
    top_k = min(request.top_k, max_k)
    bottom_k = min(request.bottom_k, max_k)
    print(f"[Config] Top-K: {top_k}, Bottom-K: {bottom_k}")

    # 1. 将 Entrez ID 转换为矩阵行索引
    print("\n[Step 1/5] 基因ID映射...")
    t0 = time.time()
    up_indices = []
    down_indices = []

    for gene_id in request.up_genes:
        gene_id_str = str(gene_id)
        if gene_id_str in gene_to_idx:
            up_indices.append(gene_to_idx[gene_id_str])

    for gene_id in request.down_genes:
        gene_id_str = str(gene_id)
        if gene_id_str in gene_to_idx:
            down_indices.append(gene_to_idx[gene_id_str])

    print(f"  有效基因: 上调 {len(up_indices)}/{len(request.up_genes)}, 下调 {len(down_indices)}/{len(request.down_genes)}")
    print(f"  耗时: {time.time()-t0:.2f}s")

    # 检查有效基因数量
    if len(up_indices) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"有效基因数量不足（上调:{len(up_indices)}, 下调:{len(down_indices)}），请检查基因ID"
        )

    # 2. 初始化 WTCS 打分器
    print("\n[Step 2/5] 初始化WTCS打分器...")
    t0 = time.time()
    try:
        scorer = WTCSScorer(up_indices, down_indices)
        print(f"  基因去重后: 上调 {scorer.n_up}, 下调 {scorer.n_down}")
        print(f"  耗时: {time.time()-t0:.2f}s")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 3. 批量计算全库WTCS分数
    print(f"\n[Step 3/5] 计算WTCS分数（全库 {N_SIGS:,} 签名）...")
    print(f"  预计时间: 10-15分钟")
    t0 = time.time()
    batch_iterator = matrix_store.get_batch_iterator(batch_size=5000)
    query_vector = np.zeros(N_GENES, dtype=np.float32)

    all_indices = []
    all_scores = []
    batch_count = 0
    total_batches = (N_SIGS + 5000 - 1) // 5000

    for start_idx, end_idx, data in batch_iterator:
        batch_scores = scorer.score(query_vector, data)
        for i, score in enumerate(batch_scores):
            all_indices.append(start_idx + i)
            all_scores.append(float(score))

        batch_count += 1
        if batch_count % 10 == 0 or batch_count == total_batches:
            elapsed = time.time() - t0
            progress = batch_count / total_batches * 100
            eta = elapsed / batch_count * (total_batches - batch_count) if batch_count > 0 else 0
            print(f"  Progress: {batch_count}/{total_batches} ({progress:.1f}%) | "
                  f"Elapsed: {elapsed/60:.1f}min | ETA: {eta/60:.1f}min")

    wtcs_time = time.time() - t0
    print(f"  ✓ WTCS计算完成，共 {len(all_scores):,} 个分数")
    print(f"  耗时: {wtcs_time/60:.1f}分钟")

    # 4. 后处理（NCS -> 聚合 -> Tau）
    print("\n[Step 4/5] 后处理（NCS归一化 → 药物聚合 → Tau计算）...")
    t0 = time.time()

    # 获取所有sig_id
    all_sig_ids = []
    idx_to_sig = {v: k for k, v in metadata_index._sig_to_idx.items()}
    for idx in all_indices:
        sig_id = idx_to_sig.get(idx, f"unknown_{idx}")
        all_sig_ids.append(sig_id)

    print(f"  准备处理 {len(all_sig_ids):,} 个签名...")

    # 执行后处理
    top_results, bottom_results = post_processor.process(
        sig_ids=all_sig_ids,
        scores=all_scores,
        return_top_k=top_k,
        return_bottom_k=bottom_k
    )
    post_time = time.time() - t0
    print(f"  ✓ 后处理完成")
    print(f"  Top结果: {len(top_results)} 个药物, Bottom结果: {len(bottom_results)} 个药物")
    print(f"  耗时: {post_time:.2f}s")

    # 5. 组装响应
    print("\n[Step 5/5] 组装响应...")
    t0 = time.time()
    top_response = [
        TauSearchResult(
            rank=r.rank,
            pert_iname=r.pert_iname,
            pert_type=r.pert_type,
            tau_score=r.tau_score,
            summary_ncs=r.summary_ncs,
            best_wtcs=r.best_wtcs,
            cell_count=r.cell_count,
            best_cell_id=r.best_cell_id,
            best_dose=r.best_dose,
            is_touchstone=r.is_touchstone
        )
        for r in top_results
    ]

    bottom_response = [
        TauSearchResult(
            rank=r.rank,
            pert_iname=r.pert_iname,
            pert_type=r.pert_type,
            tau_score=r.tau_score,
            summary_ncs=r.summary_ncs,
            best_wtcs=r.best_wtcs,
            cell_count=r.cell_count,
            best_cell_id=r.best_cell_id,
            best_dose=r.best_dose,
            is_touchstone=r.is_touchstone
        )
        for r in bottom_results
    ]

    print(f"  耗时: {time.time()-t0:.2f}s")
    print(f"\n{'='*60}")
    print(f"[Tau Search] 请求处理完成 - {time.strftime('%H:%M:%S')}")
    print(f"  总耗时: {(wtcs_time+post_time)/60:.1f}分钟")
    print(f"{'='*60}\n")

    return TauSearchResponse(
        query_up_count=len(up_indices),
        query_down_count=len(down_indices),
        top_results=top_response,
        bottom_results=bottom_response
    )
