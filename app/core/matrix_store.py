#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
矩阵数据存储访问层
使用 numpy.memmap 实现零拷贝、低内存占用的海量数据访问
"""

import os
import numpy as np
from typing import Optional, List

from ..config import MATRIX_PATH, N_GENES, N_SIGS


class MatrixStore:
    """
    矩阵数据存储访问器

    封装 numpy.memmap，提供安全的列切片访问。
    支持单条查询和批量查询，全程内存零拷贝。
    """

    _instance: Optional["MatrixStore"] = None
    _matrix: Optional[np.memmap] = None

    def __new__(cls) -> "MatrixStore":
        """单例模式确保只有一个 memmap 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._matrix is not None:
            return

        if not os.path.exists(MATRIX_PATH):
            raise FileNotFoundError(
                f"矩阵文件不存在: {MATRIX_PATH}\n"
                f"请先运行 01_build_memmap.py 生成数据文件"
            )

        # 以只读模式打开 memmap
        self._matrix = np.memmap(
            MATRIX_PATH,
            dtype='float32',
            mode='r',
            shape=(N_GENES, N_SIGS)
        )

    @property
    def shape(self) -> tuple:
        """返回矩阵形状 (N_GENES, N_SIGS)"""
        return self._matrix.shape

    def get_column(self, idx: int) -> np.ndarray:
        """
        获取指定列（一个实验签名对应的 12328 维向量）

        Args:
            idx: 列索引（0 <= idx < N_SIGS）

        Returns:
            shape=(N_GENES,) 的 float32 数组
        """
        if not 0 <= idx < N_SIGS:
            raise IndexError(f"列索引越界: {idx}, 范围 [0, {N_SIGS})")
        return self._matrix[:, idx].copy()  # copy 避免返回 memmap 视图

    def get_columns(self, indices: List[int]) -> np.ndarray:
        """
        批量获取多列数据

        Args:
            indices: 列索引列表

        Returns:
            shape=(N_GENES, len(indices)) 的 float32 数组
        """
        # 先检查所有索引合法性
        for idx in indices:
            if not 0 <= idx < N_SIGS:
                raise IndexError(f"列索引越界: {idx}, 范围 [0, {N_SIGS})")
        return self._matrix[:, indices].copy()

    def get_batch_iterator(self, batch_size: int = 10000):
        """
        生成器：按批次遍历全库所有列

        Args:
            batch_size: 每批次的列数

        Yields:
            (start_idx, end_idx, data) 元组
            data shape = (N_GENES, batch_size)
        """
        for start in range(0, N_SIGS, batch_size):
            end = min(start + batch_size, N_SIGS)
            yield start, end, self._matrix[:, start:end].copy()

    def close(self):
        """关闭 memmap（通常不需要手动调用）"""
        if self._matrix is not None:
            del self._matrix
            self._matrix = None
            MatrixStore._instance = None
