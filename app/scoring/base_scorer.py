#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
打分器策略模式基类
"""

from abc import ABC, abstractmethod
from typing import List, Tuple
import numpy as np


class BaseScorer(ABC):
    """
    打分器抽象基类

    所有打分策略（Cosine, WTCS 等）都必须继承此类
    """

    @abstractmethod
    def score(
        self,
        query: np.ndarray,
        candidates: np.ndarray
    ) -> np.ndarray:
        """
        计算查询向量与候选向量之间的分数

        Args:
            query: shape=(n_features,) 的查询向量
            candidates: shape=(n_features, n_candidates) 的候选矩阵

        Returns:
            shape=(n_candidates,) 的分数数组
        """
        pass

    @abstractmethod
    def score_batch(
        self,
        query: np.ndarray,
        candidate_iterator
    ) -> Tuple[List[int], List[float]]:
        """
        批量计算全库分数

        Args:
            query: shape=(n_features,) 的查询向量
            candidate_iterator: 生成器，产出 (start_idx, end_idx, data)

        Returns:
            (indices, scores) 元组，已按分数排序
        """
        pass
