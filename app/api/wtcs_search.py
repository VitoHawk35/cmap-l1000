#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WTCS 算法疾病逆转匹配接口
基于 CMAP 官方标准的 Weighted Connectivity Score 算法
"""

import asyncio
import json
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models.schemas import SearchRequest, SearchResponse, SearchResult
from ..core.metadata_index import MetadataIndex
from ..core.matrix_store import MatrixStore
from ..scoring.wtcs_scorer import WTCSScorer
from ..config import N_GENES, N_SIGS, ROW_NAMES_PATH
import pandas as pd

router = APIRouter()

# 单例实例
_metadata_index = None
_matrix_store = None
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


def get_gene_to_idx() -> dict:
    """获取基因 ID 到行索引的映射"""
    global _gene_to_idx
    if _gene_to_idx is None:
        row_df = pd.read_csv(ROW_NAMES_PATH)
        gene_ids = row_df['gene_id'].astype(str).tolist()
        _gene_to_idx = {gene_id: idx for idx, gene_id in enumerate(gene_ids)}
    return _gene_to_idx


@router.post("/search_wtcs", response_model=SearchResponse)
async def search_reversals_wtcs(request: SearchRequest):
    """
    WTCS 疾病特征逆转匹配（全库搜药）

    使用 CMAP 官方标准的 WTCS (Weighted Connectivity Score) 算法：
    1. 基于 Kolmogorov-Smirnov 统计量计算富集得分
    2. 分别计算上调基因和下调基因的 ES
    3. 当 ES 符号相反时：WTCS = (ES_up - ES_down) / 2

    分数解释：
    - WTCS 越负：药物逆转疾病能力越强（上调基因被抑制，下调基因被激活）
    - WTCS 越正：药物与疾病越相似（加重疾病）
    - WTCS = 0：药物无特异性逆转能力

    性能优化：
    - 分块处理：每批 5000 列，避免内存爆炸
    - 全向量化：chunk 内部使用纯 numpy 矩阵操作
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

    # 检查有效基因数量
    if len(up_indices) == 0 or len(down_indices) == 0:
        raise HTTPException(
            status_code=400,
            detail=f"有效基因数量不足（上调:{len(up_indices)}, 下调:{len(down_indices)}），请检查基因ID"
        )

    # 2. 初始化 WTCS 打分器
    try:
        scorer = WTCSScorer(up_indices, down_indices)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 3. 批量计算全库 WTCS 分数
    # 使用较小的 batch_size (5000) 因为 WTCS 计算更复杂
    batch_iterator = matrix_store.get_batch_iterator(batch_size=5000)

    # 使用 query_vector 作为占位符（WTCS 不使用它，但为了保持接口一致）
    query_vector = np.zeros(N_GENES, dtype=np.float32)

    top_indices, top_scores, bottom_indices, bottom_scores = scorer.top_k_both(
        query_vector,
        batch_iterator,
        k=request.top_k
    )

    # 4. 获取元数据
    top_metadata = metadata_index.get_by_indices(top_indices)
    bottom_metadata = metadata_index.get_by_indices(bottom_indices)

    # 5. 组装 Top 结果（最能逆转，WTCS 最负）
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

    # 6. 组装 Bottom 结果（与疾病最相似，WTCS 最正）
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

    return SearchResponse(
        query_up_count=len(up_indices),
        query_down_count=len(down_indices),
        top_results=top_results,
        bottom_results=bottom_results
    )


@router.post("/search_wtcs_stream")
async def search_reversals_wtcs_stream(request: SearchRequest):
    """
    WTCS 流式搜索（带实时进度）

    使用 Server-Sent Events (SSE) 实时推送计算进度
    前端通过 EventSource 接收进度更新

    事件格式：
    - progress: {"type": "progress", "current": 5000, "total": 473647, "percent": 1.1}
    - result: {"type": "result", "data": {...}}
    - error: {"type": "error", "message": "..."}
    """
    async def event_generator():
        try:
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

            # 检查有效基因数量
            if len(up_indices) == 0 or len(down_indices) == 0:
                yield f"data: {json.dumps({'type': 'error', 'message': f'有效基因数量不足（上调:{len(up_indices)}, 下调:{len(down_indices)}）'})}\n\n"
                return

            # 2. 初始化 WTCS 打分器
            try:
                scorer = WTCSScorer(up_indices, down_indices)
            except ValueError as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return

            # 3. 进度回调函数
            def progress_callback(current, total):
                percent = round(current / total * 100, 1)
                # 注意：这里不能直接 yield，需要通过 nonlocal 或其他方式
                # 实际上我们在生成器内部处理，所以直接 yield
                pass  # 实际实现在循环中处理

            # 4. 批量计算（带进度）
            batch_iterator = matrix_store.get_batch_iterator(batch_size=5000)
            query_vector = np.zeros(N_GENES, dtype=np.float32)

            # 初始化堆
            import heapq
            top_heap = []
            bottom_heap = []
            processed = 0
            total_batches = (N_SIGS + 4999) // 5000
            current_batch = 0

            for start_idx, end_idx, data in batch_iterator:
                batch_scores = scorer._compute_wtcs_batch(data)

                for i, score in enumerate(batch_scores):
                    idx = start_idx + i

                    # Top 堆（最负的）
                    if len(top_heap) < request.top_k:
                        heapq.heappush(top_heap, (-score, idx))
                    elif score < -top_heap[0][0]:
                        heapq.heapreplace(top_heap, (-score, idx))

                    # Bottom 堆（最正的）
                    if len(bottom_heap) < request.top_k:
                        heapq.heappush(bottom_heap, (score, idx))
                    elif score > bottom_heap[0][0]:
                        heapq.heapreplace(bottom_heap, (score, idx))

                processed += data.shape[1]
                current_batch += 1
                percent = round(processed / N_SIGS * 100, 1)

                # 发送进度更新
                yield f"data: {json.dumps({'type': 'progress', 'current': processed, 'total': N_SIGS, 'percent': percent, 'batch': current_batch, 'total_batches': total_batches})}\n\n"

                # 关键：让出控制权，让事件循环有机会发送数据
                await asyncio.sleep(0)

            # 5. 处理 Top 结果
            top_heap.sort(reverse=True)
            top_scores = [-p[0] for p in top_heap]
            top_indices = [p[1] for p in top_heap]

            # 6. 处理 Bottom 结果
            bottom_heap.sort(reverse=True)
            bottom_scores = [p[0] for p in bottom_heap]
            bottom_indices = [p[1] for p in bottom_heap]

            # 7. 获取元数据
            top_metadata = metadata_index.get_by_indices(top_indices)
            bottom_metadata = metadata_index.get_by_indices(bottom_indices)

            # 8. 组装结果
            top_results = []
            for rank, (sig, score) in enumerate(zip(top_metadata, top_scores), 1):
                top_results.append({
                    'rank': rank,
                    'sig_id': sig.sig_id,
                    'drug': sig.pert_iname,
                    'cell_line': sig.cell_id,
                    'dose': sig.pert_idose,
                    'score': float(score),
                    'pert_type': sig.pert_type
                })

            bottom_results = []
            for rank, (sig, score) in enumerate(zip(bottom_metadata, bottom_scores), 1):
                bottom_results.append({
                    'rank': rank,
                    'sig_id': sig.sig_id,
                    'drug': sig.pert_iname,
                    'cell_line': sig.cell_id,
                    'dose': sig.pert_idose,
                    'score': float(score),
                    'pert_type': sig.pert_type
                })

            # 发送最终结果
            result_data = {
                'type': 'result',
                'data': {
                    'query_up_count': len(up_indices),
                    'query_down_count': len(down_indices),
                    'top_results': top_results,
                    'bottom_results': bottom_results
                }
            }
            yield f"data: {json.dumps(result_data)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )
