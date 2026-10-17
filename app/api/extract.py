#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
特征提取接口
"""

import numpy as np
from fastapi import APIRouter, HTTPException
from typing import List

from ..models.schemas import ExtractRequest, ExtractResponse
from ..core.metadata_index import MetadataIndex
from ..core.matrix_store import MatrixStore

router = APIRouter()

# 单例实例
_metadata_index = None
_matrix_store = None


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


@router.post("/extract", response_model=ExtractResponse)
def extract_features(request: ExtractRequest):
    """
    根据药物、细胞系、浓度提取特征向量

    返回该条件下对应的 12328 维基因表达特征
    """
    metadata_index = get_metadata_index()
    matrix_store = get_matrix_store()

    # 模糊查询匹配签名
    matches = metadata_index.find_by_drug(
        drug=request.drug,
        cell_line=request.cell_line,
        dose=request.dose
    )

    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"未找到匹配的药物: {request.drug}"
        )

    if len(matches) > 1:
        # 如果有多个匹配，返回第一个并附带警告
        # 实际应用中可以考虑返回多个结果
        pass

    # 获取第一个匹配的结果
    sig = matches[0]

    # 从 memmap 提取对应列
    vector = matrix_store.get_column(sig.sig_id_idx)

    return ExtractResponse(
        sig_id=sig.sig_id,
        drug=sig.pert_iname,
        cell_line=sig.cell_id,
        dose=sig.pert_idose,
        vector=vector.tolist()
    )
