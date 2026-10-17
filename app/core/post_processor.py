#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CMAP Post-Processor
Complete CMAP Level 3 Post-Processing Pipeline

Implements the official CMAP pipeline:
Step 0: Merge with pert_info to get is_touchstone
Step 1: Calculate NCS (Normalized Connectivity Score)
Step 2: Drug-level aggregation (Perturbagen Summarization)
Step 3: Calculate Tau scores

References:
- CMAP Connectivity Map Documentation
- LINCS Level 3 Normalization and Scoring
"""

import gzip
import pandas as pd
import numpy as np
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from scipy import stats

from ..config import SIG_INFO_PATH, PERT_INFO_PATH, DEFAULT_TOP_K


@dataclass
class PostProcessedResult:
    """后处理后的结果（Perturbagen-level）"""
    rank: int
    pert_iname: str
    pert_type: str
    tau_score: float  # Tau分数（按此绝对值排序）
    summary_ncs: float  # 聚合后的NCS分数
    best_wtcs: float  # 产生summary_ncs极值那次实验的原始WTCS分数（-1~1）
    cell_count: int  # 该药物被测试过的细胞系总数
    best_cell_id: str  # 产生summary_ncs极值那次实验的cell_id
    best_dose: str  # 产生summary_ncs极值那次实验的dose
    is_touchstone: bool  # 是否是Touchstone


class CMAPPostProcessor:
    """
    CMAP L1000 Level 3 后处理器

    实现完整的后处理流程：
    1. 数据合并（与pert_info关联获取is_touchstone）
    2. NCS归一化（细胞系特异性，每次请求实时计算）
    3. 药物级聚合（每个药物取最显著的NCS，并溯源cell_id和dose）
    4. Tau分数计算（相对于Touchstone的百分位）
    """

    def __init__(self):
        """初始化后处理器，加载pert_info和sig_info到内存"""
        self.pert_info_df = None
        self.sig_info_df = None
        self._load_pert_info()
        self._load_sig_info()

    def _load_pert_info(self):
        """加载pert_info元数据到内存"""
        self.pert_info_df = pd.read_csv(
            PERT_INFO_PATH,
            sep='\t',
            compression='gzip',
            low_memory=False,
            usecols=['pert_id', 'pert_iname', 'pert_type', 'is_touchstone']
        )

    def _load_sig_info(self):
        """加载sig_info元数据到内存（轻量级，只加载必要列）"""
        self.sig_info_df = pd.read_csv(
            SIG_INFO_PATH,
            sep='\t',
            compression='gzip',
            low_memory=False,
            usecols=['sig_id', 'pert_id', 'pert_iname', 'cell_id', 'pert_type', 'pert_idose']
        )

    def process(
        self,
        sig_ids: List[str],
        scores: List[float],
        return_top_k: int = DEFAULT_TOP_K,
        return_bottom_k: int = DEFAULT_TOP_K
    ) -> Tuple[List[PostProcessedResult], List[PostProcessedResult]]:
        """
        执行完整的后处理流程

        Args:
            sig_ids: 签名ID列表（与scores一一对应）
            scores: 对应的原始WTCS分数列表
            return_top_k: 返回Top K个（最负，逆转最强）
            return_bottom_k: 返回Bottom K个（最正，与疾病最相似）

        Returns:
            (top_results, bottom_results): 两个PostProcessedResult列表
        """
        # 构建DataFrame
        df = pd.DataFrame({
            'sig_id': sig_ids,
            'score': scores
        })

        # Step 0: 数据合并，获取is_touchstone
        df = self._merge_with_pert_info(df)

        # Step 1: NCS归一化（每次请求实时计算，因为raw_score依赖于用户输入）
        df = self._calculate_ncs(df)

        # Step 2: 药物级聚合（带溯源）
        df_aggregated = self._aggregate_by_perturbagen(df)

        # Step 3: Tau分数计算
        df_aggregated = self._calculate_tau(df_aggregated)

        # Step 4: 分离Top和Bottom
        top_df = df_aggregated.nsmallest(return_top_k, 'tau_score')
        bottom_df = df_aggregated.nlargest(return_bottom_k, 'tau_score')

        # 转换为结果对象
        top_results = self._to_results(top_df, start_rank=1, ascending=True)
        bottom_results = self._to_results(bottom_df, start_rank=1, ascending=False)

        return top_results, bottom_results

    def _merge_with_pert_info(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 0: 与pert_info和sig_info合并，获取必要字段

        双保险逻辑：
        1. 尝试从pert_info获取is_touchstone
        2. 如果pert_info中不存在is_touchstone列，将所有trt_cp标记为touchstone
        """
        # 首先与sig_info合并获取cell_id, pert_id, pert_iname, pert_type, pert_idose
        df = df.merge(
            self.sig_info_df[['sig_id', 'pert_id', 'pert_iname', 'cell_id', 'pert_type', 'pert_idose']],
            on='sig_id',
            how='left'
        )

        # 将pert_id转为字符串以匹配
        df['pert_id'] = df['pert_id'].astype(str)
        self.pert_info_df['pert_id'] = self.pert_info_df['pert_id'].astype(str)

        # 与pert_info合并获取is_touchstone
        if 'is_touchstone' in self.pert_info_df.columns:
            df = df.merge(
                self.pert_info_df[['pert_id', 'is_touchstone']],
                on='pert_id',
                how='left'
            )
            # 填充缺失值
            df['is_touchstone'] = df['is_touchstone'].fillna(0).astype(int)
        else:
            # 双保险：is_touchstone列不存在，标记所有trt_cp为touchstone
            df['is_touchstone'] = (df['pert_type'] == 'trt_cp').astype(int)

        # 对于is_touchstone仍为NaN的行（pert_id匹配失败），也使用双保险策略
        df['is_touchstone'] = df['is_touchstone'].fillna(
            (df['pert_type'] == 'trt_cp').astype(int)
        ).astype(int)

        return df

    def _calculate_ncs(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 1: 计算NCS (Normalized Connectivity Score)

        关键：必须每次请求实时计算！
        因为raw_score依赖于用户的up_genes/down_genes输入。

        NCS归一化公式：
        对每个细胞系，使用Touchstone子集作为参考：
        - 计算该细胞系Touchstone的正分数均值(pos_mean)和负分数均值(neg_mean)
        - NCS = raw_score / max(|pos_mean|, |neg_mean|)
        """
        df['ncs'] = np.nan

        # 对每个细胞系分别计算
        for cell_id in df['cell_id'].unique():
            if pd.isna(cell_id):
                continue

            cell_mask = df['cell_id'] == cell_id
            cell_df = df[cell_mask]

            # 获取该细胞系的Touchstone参考
            touchstone_mask = (cell_mask) & (df['is_touchstone'] == 1)
            touchstone_scores = df.loc[touchstone_mask, 'score'].values

            if len(touchstone_scores) < 10:
                # Touchstone样本太少，跳过归一化
                df.loc[cell_mask, 'ncs'] = cell_df['score']
                continue

            # 计算正分数和负分数的均值
            pos_scores = touchstone_scores[touchstone_scores > 0]
            neg_scores = touchstone_scores[touchstone_scores < 0]

            pos_mean = np.mean(pos_scores) if len(pos_scores) > 0 else 0.01
            neg_mean = np.mean(neg_scores) if len(neg_scores) > 0 else -0.01

            # 归一化分母：取绝对值较大的均值
            denom = max(abs(pos_mean), abs(neg_mean))
            if denom < 0.001:  # 避免除零
                denom = 0.001

            # 计算NCS
            df.loc[cell_mask, 'ncs'] = cell_df['score'] / denom

        # 对于没有cell_id的行，保持原始分数
        df['ncs'] = df['ncs'].fillna(df['score'])

        return df

    def _aggregate_by_perturbagen(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 2: 药物级聚合 (Perturbagen Summarization) with Provenance
        优化版本：使用向量化操作替代 Python 循环
        """
        # 按 pert_iname 分组进行聚合
        grouped = df.groupby('pert_iname')

        # 使用 agg 进行向量化聚合
        agg_result = grouped.agg({
            'ncs': ['min', 'max', lambda x: x.abs().max()],
            'pert_type': 'first',
            'cell_id': 'nunique',
            'is_touchstone': 'max'
        }).reset_index()

        # 展平列名
        agg_result.columns = ['pert_iname', 'min_ncs', 'max_ncs', 'max_abs_ncs', 'pert_type', 'cell_count', 'is_touchstone']

        # 确定是取 min 还是 max（取绝对值大的）
        agg_result['use_max'] = agg_result['max_ncs'].abs() >= agg_result['min_ncs'].abs()
        agg_result['summary_ncs'] = agg_result.apply(
            lambda row: row['max_ncs'] if row['use_max'] else row['min_ncs'], axis=1
        )

        # 溯源：找到产生极值的行的索引
        # 创建 (pert_iname, ncs) -> 原始索引的映射
        ncs_to_idx = df.reset_index().set_index(['pert_iname', 'ncs'])['index'].to_dict()

        best_indices = []
        for _, row in agg_result.iterrows():
            target_ncs = row['summary_ncs']
            key = (row['pert_iname'], target_ncs)
            if key in ncs_to_idx:
                best_indices.append(ncs_to_idx[key])
            else:
                # 如果精确匹配失败，找最近的
                pert_df = df[df['pert_iname'] == row['pert_iname']]
                closest_idx = (pert_df['ncs'] - target_ncs).abs().idxmin()
                best_indices.append(closest_idx)

        # 获取溯源信息
        best_rows = df.loc[best_indices]
        agg_result['best_cell_id'] = best_rows['cell_id'].values
        agg_result['best_dose'] = best_rows['pert_idose'].values
        agg_result['best_wtcs'] = best_rows['score'].values

        # 转换为布尔值
        agg_result['is_touchstone'] = (agg_result['is_touchstone'] == 1)

        return agg_result[['pert_iname', 'pert_type', 'summary_ncs', 'best_wtcs', 'cell_count',
                          'best_cell_id', 'best_dose', 'is_touchstone']]

    def _calculate_tau(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 3: 计算Tau分数（向量化版本）

        Tau定义：该药物的summary_ncs在Touchstone参考分布中的百分位
        - 对于正分数：percentile * 100
        - 对于负分数：-percentile * 100
        """
        # 获取Touchstone参考分布
        touchstone_df = df[df['is_touchstone'] == True]

        if len(touchstone_df) < 10:
            # Touchstone样本太少，使用标准化分数作为替代
            mean_ncs = df['summary_ncs'].mean()
            std_ncs = df['summary_ncs'].std()
            if std_ncs > 0:
                df['tau_score'] = (df['summary_ncs'] - mean_ncs) / std_ncs * 50
            else:
                df['tau_score'] = df['summary_ncs'] * 100
            return df

        # 分离正负Touchstone分数
        touchstone_pos = touchstone_df[touchstone_df['summary_ncs'] > 0]['summary_ncs'].values
        touchstone_neg = touchstone_df[touchstone_df['summary_ncs'] < 0]['summary_ncs'].values

        # 向量化计算 tau 分数
        def compute_tau_vectorized(ncs_values, pos_ref, neg_ref):
            """向量化计算 tau 分数"""
            taus = np.zeros(len(ncs_values))

            # 正分数部分
            pos_mask = ncs_values >= 0
            if len(pos_ref) > 0:
                # 对每个正分数，计算在正Touchstone中的百分位
                for i in np.where(pos_mask)[0]:
                    taus[i] = np.mean(ncs_values[i] >= pos_ref) * 100
            else:
                taus[pos_mask] = 50

            # 负分数部分
            neg_mask = ncs_values < 0
            if len(neg_ref) > 0:
                for i in np.where(neg_mask)[0]:
                    taus[i] = -np.mean(ncs_values[i] <= neg_ref) * 100
            else:
                taus[neg_mask] = -50

            return taus

        # 使用向量化计算
        df['tau_score'] = compute_tau_vectorized(
            df['summary_ncs'].values,
            touchstone_pos,
            touchstone_neg
        )

        return df

    def _to_results(
        self,
        df: pd.DataFrame,
        start_rank: int = 1,
        ascending: bool = True
    ) -> List[PostProcessedResult]:
        """将DataFrame转换为PostProcessedResult列表

        Args:
            df: 已截取的 top/bottom DataFrame
            start_rank: 起始名次
            ascending: True 用于 top（tau 最负在前）；False 用于 bottom（tau 最正在前）
        """
        results = []

        # top：tau_score 升序（负的在前面是逆转最强）
        # bottom：tau_score 降序（最正在前面，与疾病最相似）
        # kind='mergesort' 为稳定排序，保证 ±100 饱和并列时的名次可复现
        df_sorted = df.sort_values('tau_score', ascending=ascending, kind='mergesort')

        for rank, (_, row) in enumerate(df_sorted.iterrows(), start_rank):
            results.append(PostProcessedResult(
                rank=rank,
                pert_iname=row['pert_iname'],
                pert_type=row['pert_type'],
                tau_score=float(row['tau_score']),
                summary_ncs=float(row['summary_ncs']),
                best_wtcs=float(row['best_wtcs']),
                cell_count=int(row['cell_count']),
                best_cell_id=str(row['best_cell_id']),
                best_dose=str(row['best_dose']),
                is_touchstone=bool(row['is_touchstone'])
            ))

        return results
