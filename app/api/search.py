#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
疾病逆转匹配接口（全库搜药）
"""

import numpy as np
from fastapi import APIRouter, HTTPException

from ..models.schemas import SearchRequest, SearchResponse, SearchResult
from ..core.metadata_index import MetadataIndex
from ..core.matrix_store import MatrixStore
from ..scoring.cosine_scorer import CosineScorer
from ..config import N_GENES, N_SIGS, ROW_NAMES_PATH
import pandas as pd

router = APIRouter()

# 单例实例
_metadata_index = None
_matrix_store = None
_scorer = None
_gene_to_idx = None


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


def get_scorer() -> CosineScorer:
    global _scorer
    if _scorer is None:
        _scorer = CosineScorer()
    return _scorer


def get_gene_to_idx() -> dict:
    """获取基因 ID 到行索引的映射"""
    global _gene_to_idx
    if _gene_to_idx is None:
        row_df = pd.read_csv(ROW_NAMES_PATH)
        gene_ids = row_df['gene_id'].astype(str).tolist()
        _gene_to_idx = {gene_id: idx for idx, gene_id in enumerate(gene_ids)}
    return _gene_to_idx


@router.post("/search", response_model=SearchResponse)
async def search_reversals(request: SearchRequest):
    """
    疾病特征逆转匹配（全库搜药）

    输入上调/下调基因列表，构建查询向量（up=1, down=-1, 其余=0），
    计算与全库 473647 次实验的余弦相似度，返回最能逆转疾病的 Top-50 药物。
    """
    metadata_index = get_metadata_index()
    matrix_store = get_matrix_store()
    scorer = get_scorer()
    gene_to_idx = get_gene_to_idx()

    # 防御：top_k 不能超过总数的一半，避免前后结果重叠
    max_top_k = N_SIGS // 2
    top_k = min(request.top_k, max_top_k)

    # 1. 构建查询向量
    query_vector = np.zeros(N_GENES, dtype=np.float32)

    # 上调基因设为 1
    for gene_id in request.up_genes:
        gene_id_str = str(gene_id)
        if gene_id_str in gene_to_idx:
            idx = gene_to_idx[gene_id_str]
            query_vector[idx] = 1.0

    # 下调基因设为 -1
    for gene_id in request.down_genes:
        gene_id_str = str(gene_id)
        if gene_id_str in gene_to_idx:
            idx = gene_to_idx[gene_id_str]
            query_vector[idx] = -1.0

    # 检查查询向量是否为空
    if np.linalg.norm(query_vector) == 0:
        raise HTTPException(
            status_code=400,
            detail="查询向量全为零，请检查基因 ID 是否有效"
        )

    # 2. 批量计算全库分数（同时获取最负和最正）
    batch_iterator = matrix_store.get_batch_iterator(batch_size=10000)
    top_indices, top_scores, bottom_indices, bottom_scores = scorer.top_k_both(
        query_vector,
        batch_iterator,
        k=top_k
    )

    # 3. 获取元数据
    top_metadata = metadata_index.get_by_indices(top_indices)
    bottom_metadata = metadata_index.get_by_indices(bottom_indices)

    # 4. 组装 Top 结果（最能逆转）
    top_results = []
    for rank, (sig, score) in enumerate(zip(top_metadata, top_scores), 1):
        top_results.append(SearchResult(
            rank=rank,
            sig_id=sig.sig_id,
            drug=sig.pert_iname,
            cell_line=sig.cell_id,
            dose=sig.pert_idose,
            score=float(score),
            pert_type=sig.pert_type
        ))

    # 5. 组装 Bottom 结果（最相似）
    bottom_results = []
    for rank, (sig, score) in enumerate(zip(bottom_metadata, bottom_scores), 1):
        bottom_results.append(SearchResult(
            rank=rank,
            sig_id=sig.sig_id,
            drug=sig.pert_iname,
            cell_line=sig.cell_id,
            dose=sig.pert_idose,
            score=float(score),
            pert_type=sig.pert_type
        ))

    return SearchResponse(
        query_up_count=len(request.up_genes),
        query_down_count=len(request.down_genes),
        top_results=top_results,
        bottom_results=bottom_results
    )
