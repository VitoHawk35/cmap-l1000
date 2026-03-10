#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
余弦相似度打分器
用于疾病特征逆转匹配
"""

import numpy as np
from typing import List, Tuple

from .base_scorer import BaseScorer
from ..config import N_GENES


class CosineScorer(BaseScorer):
    """
    余弦相似度打分器

    用于计算查询向量（疾病特征向量）与候选向量之间的余弦相似度。
    分数越负表示越能逆转疾病。
    """

    def __init__(self):
        pass

    def score(
        self,
        query: np.ndarray,
        candidates: np.ndarray
    ) -> np.ndarray:
        """
        计算余弦相似度

        Args:
            query: shape=(N_GENES,) 的查询向量
            candidates: shape=(N_GENES, n_candidates) 的候选矩阵

        Returns:
            shape=(n_candidates,) 的余弦相似度分数
        """
        # 确保维度正确
        if query.shape != (N_GENES,):
            raise ValueError(f"query 形状错误: {query.shape}, 应为 ({N_GENES},)")

        if candidates.shape[0] != N_GENES:
            raise ValueError(f"candidates 形状错误: {candidates.shape}, 第一维应为 {N_GENES}")

        # 计算余弦相似度
        # cos_sim = (q · c) / (||q|| * ||c||)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return np.zeros(candidates.shape[1])

        # 计算点积
        dot_product = np.dot(query, candidates)

        # 计算候选向量的模
        candidates_norm = np.linalg.norm(candidates, axis=0)

        # 避免除以零
        candidates_norm = np.where(candidates_norm == 0, 1, candidates_norm)

        # 计算余弦相似度
        cosine_sim = dot_product / (query_norm * candidates_norm)

        return cosine_sim

    def score_batch(
        self,
        query: np.ndarray,
        candidate_iterator
    ) -> Tuple[List[int], List[float]]:
        """
        批量计算全库分数

        Args:
            query: shape=(N_GENES,) 的查询向量
            candidate_iterator: 生成器，产出 (start_idx, end_idx, data)

        Returns:
            (indices, scores) 元组，已按分数升序排列（最负在前）
        """
        all_scores = []
        all_indices = []

        for start_idx, end_idx, data in candidate_iterator:
            # data shape: (N_GENES, batch_size)
            batch_scores = self.score(query, data)

            # 记录分数和索引
            for i, score in enumerate(batch_scores):
                all_indices.append(start_idx + i)
                all_scores.append(score)

        # 按分数升序排序（最负的在前，即最能逆转疾病的在前）
        sorted_pairs = sorted(zip(all_indices, all_scores), key=lambda x: x[1])
        indices = [p[0] for p in sorted_pairs]
        scores = [p[1] for p in sorted_pairs]

        return indices, scores

    def top_k(
        self,
        query: np.ndarray,
        candidate_iterator,
        k: int = 50
    ) -> Tuple[List[int], List[float]]:
        """
        高效获取 Top-K 最负的分数

        使用堆优化，避免存储全部分数

        Args:
            query: shape=(N_GENES,) 的查询向量
            candidate_iterator: 生成器
            k: 返回前 K 个

        Returns:
            (indices, scores) 元组，已按分数升序排列
        """
        import heapq

        # 使用最大堆（存储负数实现）
        # heap 元素: (score, index)，取最负的（即最小的）
        heap = []

        for start_idx, end_idx, data in candidate_iterator:
            batch_scores = self.score(query, data)

            for i, score in enumerate(batch_scores):
                idx = start_idx + i

                if len(heap) < k:
                    heapq.heappush(heap, (score, idx))
                elif score < heap[0][0]:  # 比当前最大堆顶还小（更负）
                    heapq.heapreplace(heap, (score, idx))

        # 排序输出（升序，最负在前）
        heap.sort()
        scores = [p[0] for p in heap]
        indices = [p[1] for p in heap]

        return indices, scores
