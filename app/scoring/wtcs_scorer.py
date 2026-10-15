#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WTCS (Weighted Connectivity Score) 打分器
基于 Kolmogorov-Smirnov 统计量的富集得分算法

CMAP 官方标准算法，用于衡量药物对疾病特征的逆转能力
"""

import heapq
import numpy as np
from typing import List, Tuple, Optional, Callable

from .base_scorer import BaseScorer
from ..config import N_GENES, N_SIGS


class WTCSScorer(BaseScorer):
    """
    WTCS 打分器 - CMAP 官方标准算法

    算法原理：
    1. 对每列（药物实验）的 12328 个基因按表达量降序排列
    2. 计算上调基因在该排序列表中的富集得分 ES_up
    3. 计算下调基因的富集得分 ES_down
    4. 若 ES_up 和 ES_down 符号相反：WTCS = (ES_up - ES_down) / 2
       否则：WTCS = 0（说明药物无特异性逆转能力）

    性能优化：
    - 分块处理：将 473647 列分批处理（避免内存爆炸）
    - 全向量化：每个 chunk 内部使用纯 numpy 矩阵操作，无 Python 循环
    - 流式堆：使用最大堆维护 Top-K，无需存储全部分数

    逆转搜索：
    - WTCS 越负，表示药物逆转疾病能力越强
    - 需要找 WTCS 最小的（最负）药物
    """

    def __init__(self, up_gene_indices: List[int], down_gene_indices: List[int]):
        """
        初始化 WTCS 打分器

        Args:
            up_gene_indices: 上调基因在 12328 维中的索引列表（0-based）
            down_gene_indices: 下调基因在 12328 维中的索引列表（0-based）
        """
        # 去重：移除重复基因索引
        up_unique = list(set(up_gene_indices))
        down_unique = list(set(down_gene_indices))

        # 检查上下调基因是否有重叠
        overlap = set(up_unique) & set(down_unique)
        if overlap:
            # 从两个列表中都移除重叠的基因
            up_unique = [idx for idx in up_unique if idx not in overlap]
            down_unique = [idx for idx in down_unique if idx not in overlap]
            print(f"[WTCS Warning] 上调和下调基因存在 {len(overlap)} 个重叠项，已自动移除: {list(overlap)[:5]}...")

        if len(up_unique) == 0:
            raise ValueError(f"去重后上调基因数量不足（上调:{len(up_unique)}, 下调:{len(down_unique)}）")

        self.up_indices = np.array(up_unique, dtype=np.int32)
        self.down_indices = np.array(down_unique, dtype=np.int32) if down_unique else np.array([], dtype=np.int32)
        self.n_up = len(up_unique)
        self.n_down = len(down_unique)

        # 预计算 query 指示向量 (N_GENES,)
        # 1 表示该位置是 query 基因，0 表示不是
        self._up_indicator = np.zeros(N_GENES, dtype=np.float32)
        self._up_indicator[self.up_indices] = 1.0

        self._down_indicator = np.zeros(N_GENES, dtype=np.float32)
        if self.n_down > 0:
            self._down_indicator[self.down_indices] = 1.0

        if self.n_up == 0:
            raise ValueError("上调基因列表不能为空")

    def _compute_es_batch(
        self,
        sorted_indices: np.ndarray,
        indicator: np.ndarray,
        n_query: int
    ) -> np.ndarray:
        """
        向量化计算富集得分 (Enrichment Score)
        """
        batch_size = sorted_indices.shape[1]

        # 使用高级索引获取 hit 矩阵 (N_GENES, batch_size)
        hit = indicator[sorted_indices].reshape(N_GENES, batch_size)

        # 累积命中分布（query 基因在排序列表中的累积比例）
        cumsum_hit = np.cumsum(hit, axis=0) / n_query  # (N_GENES, batch_size)

        # 累积缺失分布（非 query 基因在排序列表中的累积比例）
        cumsum_miss = np.cumsum(1.0 - hit, axis=0) / (N_GENES - n_query)

        # 计算偏差（Kolmogorov-Smirnov 统计量）
        diff = cumsum_hit - cumsum_miss  # (N_GENES, batch_size)

        # 找到最大偏差的绝对值及其位置
        abs_diff = np.abs(diff)
        max_indices = np.argmax(abs_diff, axis=0)  # (batch_size,)

        # 获取最大偏差值（保留符号）
        max_diff = np.take_along_axis(
            diff,
            max_indices.reshape(1, -1),
            axis=0
        ).flatten()  # (batch_size,)

        return max_diff

    def _compute_wtcs_batch(self, chunk: np.ndarray) -> np.ndarray:
        """
        向量化计算 WTCS 分数
        """
        batch_size = chunk.shape[1]

        # 1. 沿 axis=0 降序排序，获取排序索引
        sorted_indices = np.argsort(-chunk, axis=0, kind='mergesort')  # (N_GENES, batch_size)

        # 2. 计算 ES_up（上调基因的富集得分）
        es_up = self._compute_es_batch(sorted_indices, self._up_indicator, self.n_up)

        # 3. 计算 ES_down（下调基因的富集得分）
        if self.n_down > 0:
            es_down = self._compute_es_batch(sorted_indices, self._down_indicator, self.n_down)

            # 4. 计算 WTCS
            # 如果 ES_up 和 ES_down 符号相反，WTCS = (ES_up - ES_down) / 2
            # 否则 WTCS = 0
            opposite_signs = (es_up * es_down) < 0  # 符号相反

            wtcs = np.zeros(batch_size, dtype=np.float32)
            wtcs[opposite_signs] = (es_up[opposite_signs] - es_down[opposite_signs]) / 2.0
        else:
            # 下调为空时，WTCS = ES_up（仅考虑上调基因的富集）
            wtcs = es_up

        return wtcs

    def score(
        self,
        query: np.ndarray,
        candidates: np.ndarray
    ) -> np.ndarray:
        """
        计算 WTCS 分数

        注意：WTCS 不使用 query 参数，因为基因信息已在初始化时通过 up/down indices 传入
        但为了保持接口一致性，保留 query 参数

        Args:
            query: 未使用（保持接口一致性）
            candidates: (N_GENES, n_candidates) 候选矩阵

        Returns:
            wtcs: (n_candidates,) WTCS 分数
        """
        if candidates.shape[0] != N_GENES:
            raise ValueError(f"candidates 形状错误: {candidates.shape}, 第一维应为 {N_GENES}")

        return self._compute_wtcs_batch(candidates)

    def score_batch(
        self,
        query: np.ndarray,
        candidate_iterator
    ) -> Tuple[List[int], List[float]]:
        """
        批量计算全库 WTCS 分数

        Args:
            query: 未使用
            candidate_iterator: 生成器，产出 (start_idx, end_idx, data)

        Returns:
            (indices, scores) 元组，已按 WTCS 升序排列（最负在前）
        """
        all_scores = []
        all_indices = []

        for start_idx, end_idx, data in candidate_iterator:
            batch_scores = self._compute_wtcs_batch(data)

            for i, score in enumerate(batch_scores):
                all_indices.append(start_idx + i)
                all_scores.append(float(score))

        # 按 WTCS 升序排序（最负的在前，逆转能力最强）
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
        高效获取 WTCS 最小的 Top-K 药物（逆转能力最强）

        使用最大堆优化，避免存储全部分数

        Args:
            query: 未使用
            candidate_iterator: 生成器
            k: 返回前 K 个

        Returns:
            (indices, scores) 元组，已按 WTCS 升序排列（最负在前）
        """
        # 最大堆（存储负数实现）：保存当前最小的 k 个 WTCS（最负的）
        heap = []

        for start_idx, end_idx, data in candidate_iterator:
            batch_scores = self._compute_wtcs_batch(data)

            for i, score in enumerate(batch_scores):
                idx = start_idx + i

                if len(heap) < k:
                    # 堆未满，直接加入（存负数实现最大堆）
                    heapq.heappush(heap, (-score, idx))
                elif score < -heap[0][0]:  # 当前分数比堆顶更小（更负）
                    heapq.heapreplace(heap, (-score, idx))

        # 排序输出（升序，最负在前）
        heap.sort(reverse=True)  # 负数大的在前（即 score 小的在前）
        scores = [-p[0] for p in heap]
        indices = [p[1] for p in heap]

        return indices, scores

    def top_k_both(
        self,
        query: np.ndarray,
        candidate_iterator,
        k: int = 100
    ) -> Tuple[List[int], List[float], List[int], List[float]]:
        """
        同时获取 WTCS 最小的 Top-K（逆转最强）和最大的 Bottom-K（加重最强）

        Args:
            query: 未使用
            candidate_iterator: 生成器
            k: 返回 K 个

        Returns:
            (top_indices, top_scores, bottom_indices, bottom_scores)
            top: WTCS 最小的（最负，逆转能力最强）
            bottom: WTCS 最大的（最正，与疾病最相似/加重）
        """
        # 最小堆：保存最负的（WTCS 小的）
        top_heap = []

        # 最大堆：保存最正的（WTCS 大的）
        bottom_heap = []

        for start_idx, end_idx, data in candidate_iterator:
            batch_scores = self._compute_wtcs_batch(data)

            for i, score in enumerate(batch_scores):
                idx = start_idx + i

                # Top 堆（最负的，逆转最强）
                if len(top_heap) < k:
                    heapq.heappush(top_heap, (-score, idx))
                elif score < -top_heap[0][0]:  # 更负
                    heapq.heapreplace(top_heap, (-score, idx))

                # Bottom 堆（最正的，与疾病最相似）
                if len(bottom_heap) < k:
                    heapq.heappush(bottom_heap, (score, idx))
                elif score > bottom_heap[0][0]:  # 更正
                    heapq.heapreplace(bottom_heap, (score, idx))

        # 处理 Top 结果（最负的）
        top_heap.sort(reverse=True)
        top_scores = [-p[0] for p in top_heap]
        top_indices = [p[1] for p in top_heap]

        # 处理 Bottom 结果（最正的）
        bottom_heap.sort(reverse=True)
        bottom_scores = [p[0] for p in bottom_heap]
        bottom_indices = [p[1] for p in bottom_heap]

        return top_indices, top_scores, bottom_indices, bottom_scores

    def top_k_both_with_progress(
        self,
        query: np.ndarray,
        candidate_iterator,
        k: int = 100,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[List[int], List[float], List[int], List[float]]:
        """
        同时获取 Top-K 和 Bottom-K，支持进度回调

        Args:
            query: 未使用
            candidate_iterator: 生成器
            k: 返回 K 个
            progress_callback: 进度回调函数(current, total)

        Returns:
            (top_indices, top_scores, bottom_indices, bottom_scores)
        """
        top_heap = []
        bottom_heap = []
        processed = 0

        for start_idx, end_idx, data in candidate_iterator:
            batch_scores = self._compute_wtcs_batch(data)

            for i, score in enumerate(batch_scores):
                idx = start_idx + i

                # Top 堆（最负的）
                if len(top_heap) < k:
                    heapq.heappush(top_heap, (-score, idx))
                elif score < -top_heap[0][0]:
                    heapq.heapreplace(top_heap, (-score, idx))

                # Bottom 堆（最正的）
                if len(bottom_heap) < k:
                    heapq.heappush(bottom_heap, (score, idx))
                elif score > bottom_heap[0][0]:
                    heapq.heapreplace(bottom_heap, (score, idx))

            processed += data.shape[1]
            if progress_callback:
                progress_callback(processed, N_SIGS)

        # 处理结果
        top_heap.sort(reverse=True)
        top_scores = [-p[0] for p in top_heap]
        top_indices = [p[1] for p in top_heap]

        bottom_heap.sort(reverse=True)
        bottom_scores = [p[0] for p in bottom_heap]
        bottom_indices = [p[1] for p in bottom_heap]

        return top_indices, top_scores, bottom_indices, bottom_scores
