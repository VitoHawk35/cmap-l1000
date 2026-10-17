#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
搜索结果导出接口
导出 Top/Bottom 结果为 CSV
"""

import io
import zipfile
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models.schemas import SearchRequest, SearchResult
from ..core.metadata_index import MetadataIndex
from ..core.matrix_store import MatrixStore
from ..scoring.cosine_scorer import CosineScorer
from ..config import N_GENES, ROW_NAMES_PATH
import pandas as pd
import numpy as np

router = APIRouter()

# 单例实例（复用 search.py 的实例）
_metadata_index = None
_matrix_store = None
_scorer = None
_gene_to_idx = None


def get_metadata_index():
    global _metadata_index
    if _metadata_index is None:
        _metadata_index = MetadataIndex()
    return _metadata_index


def get_matrix_store():
    global _matrix_store
    if _matrix_store is None:
        _matrix_store = MatrixStore()
    return _matrix_store


def get_scorer():
    global _scorer
    if _scorer is None:
        _scorer = CosineScorer()
    return _scorer


def get_gene_to_idx():
    """获取基因 ID 到行索引的映射"""
    global _gene_to_idx
    if _gene_to_idx is None:
        row_df = pd.read_csv(ROW_NAMES_PATH)
        gene_ids = row_df['gene_id'].astype(str).tolist()
        _gene_to_idx = {gene_id: idx for idx, gene_id in enumerate(gene_ids)}
    return _gene_to_idx


def _results_to_csv(results: List[SearchResult]) -> str:
    """将结果列表转换为 CSV 字符串"""
    data = []
    for r in results:
        data.append({
            'rank': r.rank,
            'sig_id': r.sig_id,
            'drug': r.drug,
            'cell_line': r.cell_line,
            'dose': r.dose,
            'score': f"{r.score:.6f}"
        })
    df = pd.DataFrame(data)
    return df.to_csv(index=False, encoding='utf-8')


@router.post("/export")
def export_results(request: SearchRequest):
    """
    导出搜索结果为 CSV（打包为 zip）

    返回包含两个文件的 zip：
    - top_reversals.csv: 最能逆转疾病的药物（最负相关）
    - bottom_matches.csv: 与疾病最相似的药物（最正相关）
    """
    metadata_index = get_metadata_index()
    matrix_store = get_matrix_store()
    scorer = get_scorer()
    gene_to_idx = get_gene_to_idx()

    # 1. 构建查询向量
    query_vector = np.zeros(N_GENES, dtype=np.float32)

    for gene_id in request.up_genes:
        gene_id_str = str(gene_id)
        if gene_id_str in gene_to_idx:
            idx = gene_to_idx[gene_id_str]
            query_vector[idx] = 1.0

    for gene_id in request.down_genes:
        gene_id_str = str(gene_id)
        if gene_id_str in gene_to_idx:
            idx = gene_to_idx[gene_id_str]
            query_vector[idx] = -1.0

    if np.linalg.norm(query_vector) == 0:
        raise HTTPException(
            status_code=400,
            detail="查询向量全为零，请检查基因 ID 是否有效"
        )

    # 2. 批量计算全库分数
    batch_iterator = matrix_store.get_batch_iterator(batch_size=10000)
    top_indices, top_scores, bottom_indices, bottom_scores = scorer.top_k_both(
        query_vector,
        batch_iterator,
        k=request.top_k
    )

    # 3. 获取元数据并组装结果
    top_metadata = metadata_index.get_by_indices(top_indices)
    bottom_metadata = metadata_index.get_by_indices(bottom_indices)

    top_results = []
    for rank, (sig, score) in enumerate(zip(top_metadata, top_scores), 1):
        top_results.append(SearchResult(
            rank=rank,
            sig_id=sig.sig_id,
            drug=sig.pert_iname,
            cell_line=sig.cell_id,
            dose=sig.pert_idose,
            score=float(score)
        ))

    bottom_results = []
    for rank, (sig, score) in enumerate(zip(bottom_metadata, bottom_scores), 1):
        bottom_results.append(SearchResult(
            rank=rank,
            sig_id=sig.sig_id,
            drug=sig.pert_iname,
            cell_line=sig.cell_id,
            dose=sig.pert_idose,
            score=float(score)
        ))

    # 4. 生成 CSV 内容
    top_csv = _results_to_csv(top_results)
    bottom_csv = _results_to_csv(bottom_results)

    # 5. 打包为 zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('top_reversals.csv', top_csv)
        zip_file.writestr('bottom_matches.csv', bottom_csv)

    zip_buffer.seek(0)

    # 6. 返回流式响应
    headers = {
        'Content-Disposition': 'attachment; filename=cmap_search_results.zip'
    }
    return StreamingResponse(
        zip_buffer,
        media_type='application/zip',
        headers=headers
    )
