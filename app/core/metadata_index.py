#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
元数据索引管理
基于 sig_info 构建高效的内存索引，支持模糊查询
"""

import gzip
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from ..config import SIG_INFO_PATH, COL_NAMES_PATH, N_SIGS


@dataclass
class SigMetadata:
    """单个签名的元数据结构"""
    sig_id: str
    pert_iname: str  # 药物名称
    cell_id: str     # 细胞系
    pert_idose: str  # 剂量
    pert_time: str   # 处理时间
    sig_id_idx: int  # 在矩阵中的列索引


class MetadataIndex:
    """
    sig_info 元数据索引

    提供高效的药物/细胞系/剂量查询能力
    """

    _instance: Optional["MetadataIndex"] = None

    def __new__(cls) -> "MetadataIndex":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_df') and self._df is not None:
            return

        # 加载 sig_info 元数据
        self._df = self._load_sig_info()

        # 加载 sig_id 到列索引的映射
        self._sig_to_idx = self._build_sig_index()

        # 构建查询索引
        self._build_query_indices()

    def _load_sig_info(self) -> pd.DataFrame:
        """加载 sig_info 文件"""
        df = pd.read_csv(SIG_INFO_PATH, sep='\t', compression='gzip', low_memory=False)

        # 确保必要的列存在
        required_cols = ['sig_id', 'pert_iname', 'cell_id', 'pert_idose']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"sig_info 缺少必要列: {col}")

        return df

    def _build_sig_index(self) -> Dict[str, int]:
        """构建 sig_id -> 列索引的映射"""
        col_df = pd.read_csv(COL_NAMES_PATH)
        sig_ids = col_df['sig_id'].tolist()

        if len(sig_ids) != N_SIGS:
            raise ValueError(f"列名数量 {len(sig_ids)} 与预期 {N_SIGS} 不符")

        return {sig_id: idx for idx, sig_id in enumerate(sig_ids)}

    def _build_query_indices(self):
        """构建用于模糊查询的索引"""
        # 标准化药物名称（转小写）
        self._df['pert_iname_lower'] = self._df['pert_iname'].str.lower()

        # 构建倒排索引：药物名 -> [签名索引列表]
        self._drug_index: Dict[str, List[int]] = {}
        for idx, row in self._df.iterrows():
            drug = row['pert_iname_lower']
            if drug not in self._drug_index:
                self._drug_index[drug] = []
            self._drug_index[drug].append(idx)

        # 细胞系索引
        self._cell_index: Dict[str, List[int]] = {}
        for idx, row in self._df.iterrows():
            cell = row['cell_id']
            if cell not in self._cell_index:
                self._cell_index[cell] = []
            self._cell_index[cell].append(idx)

    def find_by_drug(
        self,
        drug: str,
        cell_line: Optional[str] = None,
        dose: Optional[str] = None
    ) -> List[SigMetadata]:
        """
        模糊查询药物对应的签名

        Args:
            drug: 药物名称（支持模糊匹配，忽略大小写）
            cell_line: 可选的细胞系过滤
            dose: 可选的剂量过滤

        Returns:
            匹配的签名元数据列表
        """
        drug_lower = drug.lower()

        # 模糊匹配药物名
        matched_indices = []
        for d, indices in self._drug_index.items():
            if drug_lower in d or d in drug_lower:
                matched_indices.extend(indices)

        if not matched_indices:
            return []

        # 应用额外过滤
        results = []
        for idx in matched_indices:
            row = self._df.iloc[idx]

            if cell_line and row['cell_id'] != cell_line:
                continue
            if dose and row['pert_idose'] != dose:
                continue

            sig_id = row['sig_id']
            sig_idx = self._sig_to_idx.get(sig_id)

            if sig_idx is not None:
                results.append(SigMetadata(
                    sig_id=sig_id,
                    pert_iname=row['pert_iname'],
                    cell_id=row['cell_id'],
                    pert_idose=row.get('pert_idose', ''),
                    pert_time=row.get('pert_time', ''),
                    sig_id_idx=sig_idx
                ))

        return results

    def get_by_indices(self, indices: List[int]) -> List[SigMetadata]:
        """
        根据列索引批量获取元数据

        Args:
            indices: 列索引列表

        Returns:
            签名元数据列表
        """
        # 构建反向映射：列索引 -> sig_id
        idx_to_sig = {v: k for k, v in self._sig_to_idx.items()}

        results = []
        for idx in indices:
            sig_id = idx_to_sig.get(idx)
            if sig_id is None:
                continue

            # 在 df 中找到对应行
            row = self._df[self._df['sig_id'] == sig_id]
            if len(row) == 0:
                continue

            row = row.iloc[0]
            results.append(SigMetadata(
                sig_id=sig_id,
                pert_iname=row['pert_iname'],
                cell_id=row['cell_id'],
                pert_idose=row.get('pert_idose', ''),
                pert_time=row.get('pert_time', ''),
                sig_id_idx=idx
            ))

        return results

    def get_by_sig_id(self, sig_id: str) -> Optional[SigMetadata]:
        """根据 sig_id 获取元数据"""
        row = self._df[self._df['sig_id'] == sig_id]
        if len(row) == 0:
            return None

        row = row.iloc[0]
        sig_idx = self._sig_to_idx.get(sig_id)

        return SigMetadata(
            sig_id=sig_id,
            pert_iname=row['pert_iname'],
            cell_id=row['cell_id'],
            pert_idose=row.get('pert_idose', ''),
            pert_time=row.get('pert_time', ''),
            sig_id_idx=sig_idx if sig_idx is not None else -1
        )
