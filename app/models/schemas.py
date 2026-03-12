#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pydantic 模型定义
"""

from typing import List, Optional
from pydantic import BaseModel


# ============ 接口1: 特征提取 ============

class ExtractRequest(BaseModel):
    """特征提取请求"""
    drug: str                    # 药物名称
    cell_line: Optional[str] = None  # 细胞系（可选）
    dose: Optional[str] = None       # 剂量（可选）


class ExtractResponse(BaseModel):
    """特征提取响应"""
    sig_id: str                  # 签名 ID
    drug: str                    # 药物名称
    cell_line: str               # 细胞系
    dose: str                    # 剂量
    vector: List[float]          # 12328 维特征向量


# ============ 接口2: 疾病逆转匹配 ============

class SearchRequest(BaseModel):
    """疾病逆转匹配请求"""
    up_genes: List[int]          # 上调基因 Entrez ID 列表
    down_genes: List[int]        # 下调基因 Entrez ID 列表
    top_k: int = 50              # 返回 Top-K 结果


class SearchResult(BaseModel):
    """单个搜索结果"""
    rank: int                    # 排名
    sig_id: str                  # 签名 ID
    drug: str                    # 药物名称
    cell_line: str               # 细胞系
    dose: str                    # 剂量
    score: float                 # 余弦相似度分数
    pert_type: str = ""          # 扰动类型


class SearchResponse(BaseModel):
    """疾病逆转匹配响应"""
    query_up_count: int          # 查询中上调基因数量
    query_down_count: int        # 查询中下调基因数量
    top_results: List[SearchResult]     # Top-K 结果（最能逆转，最负）
    bottom_results: List[SearchResult]  # Bottom-K 结果（最相似，最正）
