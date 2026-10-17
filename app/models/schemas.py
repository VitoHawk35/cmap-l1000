#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pydantic 模型定义
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from ..config import DEFAULT_TOP_K


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
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=5000)  # 返回 Top-K 结果


class SearchResult(BaseModel):
    """单个搜索结果"""
    rank: int                    # 排名
    sig_id: str                  # 签名 ID
    drug: str                    # 药物名称
    cell_line: str               # 细胞系
    dose: str                    # 剂量
    score: float                 # 余弦相似度分数
    pert_type: str = ""          # 扰动类型
    is_touchstone: bool = False  # 是否为 Touchstone


class SearchResponse(BaseModel):
    """疾病逆转匹配响应"""
    query_up_count: int          # 查询中上调基因数量
    query_down_count: int        # 查询中下调基因数量
    top_results: List[SearchResult]     # Top-K 结果（最能逆转，最负）
    bottom_results: List[SearchResult]  # Bottom-K 结果（最相似，最正）


# ============ 接口3: Tau搜索（Perturbagen-level，后处理完整流程） ============

class TauSearchRequest(BaseModel):
    """Tau分数搜索请求（完整后处理流程）"""
    up_genes: List[int]          # 上调基因 Entrez ID 列表
    down_genes: List[int]        # 下调基因 Entrez ID 列表
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=5000)     # 返回 Top-K 结果
    bottom_k: int = Field(DEFAULT_TOP_K, ge=1, le=5000)  # 返回 Bottom-K 结果


class TauSearchResult(BaseModel):
    """Tau搜索单个结果（Perturbagen-level）"""
    rank: int                    # 排名
    pert_iname: str              # 药物名称
    pert_type: str               # 扰动类型
    tau_score: float             # Tau分数（按此排序）
    summary_ncs: float           # 聚合后的NCS分数
    best_wtcs: float             # 产生极值那次实验的原始WTCS分数（-1~1）
    cell_count: int              # 测试细胞系数
    best_cell_id: str            # 产生极值的细胞系
    best_dose: str               # 产生极值的剂量
    is_touchstone: bool          # 是否Touchstone


class TauSearchResponse(BaseModel):
    """Tau搜索响应"""
    query_up_count: int          # 查询中上调基因数量
    query_down_count: int        # 查询中下调基因数量
    top_results: List[TauSearchResult]     # Top-K 结果（tau最负，逆转最强）
    bottom_results: List[TauSearchResult]  # Bottom-K 结果（tau最正，与疾病最相似）


# ============ 接口4: Tau异步任务 ============

class TauJobSubmitResponse(BaseModel):
    """提交Tau任务响应"""
    job_id: str
    status: str
    message: str


class TauJobStatusResponse(BaseModel):
    """查询Tau任务状态响应"""
    job_id: str
    status: str                  # pending, running, completed, failed
    created_at: float
    updated_at: float
    progress: Optional[dict] = None
    result: Optional[TauSearchResponse] = None
    error: Optional[str] = None
