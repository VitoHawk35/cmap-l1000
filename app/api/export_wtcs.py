#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WTCS 搜索结果导出接口
导出 WTCS Top/Bottom 结果为 CSV
"""

import io
import zipfile
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models.schemas import SearchRequest, SearchResult
from ..core.metadata_index import MetadataIndex
from ..core.matrix_store import MatrixStore
from ..scoring.wtcs_scorer import WTCSScorer
from ..config import N_GENES, ROW_NAMES_PATH
import pandas as pd
import numpy as np

router = APIRouter()

# 单例实例
_metadata_index = None
_matrix_store = None
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
            'wtcs_score': f"{r.score:.6f}"
        })
    df = pd.DataFrame(data)
    return df.to_csv(index=False, encoding='utf-8')


@router.post("/export_wtcs")
async def export_results_wtcs(request: SearchRequest):
    """
    导出 WTCS 搜索结果为 CSV（打包为 zip）

    返回包含两个文件的 zip：
    - top_reversals.csv: 最能逆转疾病的药物（WTCS 最负）
    - bottom_matches.csv: 与疾病最相似的药物（WTCS 最正）
    """
    metadata_index = get_metadata_index()
    matrix_store = get_matrix_store()
    gene_to_idx = get_gene_to_idx()

    # 1. 将 Entrez ID 转换为矩阵行索引
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

    if len(up_indices) == 0 or len(down_indices) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"有效基因数量不足（上调:{len(up_indices)}, 下调:{len(down_indices)}）"
        )

    # 2. 初始化 WTCS 打分器
    try:
        scorer = WTCSScorer(up_indices, down_indices)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 3. 批量计算全库 WTCS 分数
    batch_iterator = matrix_store.get_batch_iterator(batch_size=5000)
    query_vector = np.zeros(N_GENES, dtype=np.float32)

    top_indices, top_scores, bottom_indices, bottom_scores = scorer.top_k_both(
        query_vector,
        batch_iterator,
        k=request.top_k
    )

    # 4. 获取元数据并组装结果
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

    # 5. 生成 CSV 内容
    top_csv = _results_to_csv(top_results)
    bottom_csv = _results_to_csv(bottom_results)

    # 6. 打包为 zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('top_reversals_wtcs.csv', top_csv)
        zip_file.writestr('bottom_matches_wtcs.csv', bottom_csv)

    zip_buffer.seek(0)

    # 7. 返回流式响应
    headers = {
        'Content-Disposition': 'attachment; filename=cmap_wtcs_results.zip'
    }
    return StreamingResponse(
        zip_buffer,
        media_type='application/zip',
        headers=headers
    )
