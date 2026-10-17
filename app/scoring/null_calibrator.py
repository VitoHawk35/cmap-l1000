#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C3 方案 B：查询内随机签名 null → 经验 p 值 / BH-FDR / null z。

与 LMNA L4（backend/drug_scorer.py::drug_null）使用同一套算法。

符号约定（本仓库对外约定）
--------------------------
    xsum = Σz(up) − Σz(down)          **负 = 逆转**（与 WTCS/Tau 一致）
    p_reversal = (#{null <= xsum} + 1) / (M + 1)
        null 也是同样大小的随机签名（同样按 up/down 分组），其 xsum 越小越
        “逆转”；因此 null <= xsum 表示“随机签名至少和观测一样逆转”。
        p_reversal 越小 = 观测逆转越极端。
    null_z = (xsum − mean(null)) / sd(null)
        **负 = 比随机更逆转**（与 LMNA 的 null_z 方向一致；因为本仓库以负为逆转）。
    fdr_reversal = BH(p_reversal)，对全部药物做多重校正。

注意：LMNA 对外 score = −mimic（高分=逆转），本仓库对外 xsum 直接是
mimic 方向（负分=逆转），两个仓库各自保持自己的对外约定；底层 null
统计量相同。
"""

import gc
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import (
    DRUG_MEDIAN_GENE_IDS_PATH,
    DRUG_MEDIAN_MATRIX_PATH,
    DRUG_MEDIAN_NAMES_PATH,
    NULL_CALIBRATION_BATCH,
    NULL_CALIBRATION_MIN_GENES,
    NULL_CALIBRATION_N,
    NULL_CALIBRATION_SEED,
)


RESULT_COLUMNS = ["pert_iname", "xsum", "p_reversal", "fdr_reversal", "null_z"]

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_landmark_genes"
STATUS_UNAVAILABLE = "unavailable"


def benjamini_hochberg(p_values):
    """
    Benjamini-Hochberg FDR 校正。

    q_(i) = min_{j >= i} p_(j) * n / j（p 升序），并截断到 [0, 1]。
    与 scipy.stats.false_discovery_control(method="bh") 等价；本仓库运行
    环境为 Python 3.8 + scipy 1.10（scipy 的该函数从 1.11 起才提供），
    因此自实现并由测试与 scipy 对比。
    """
    p = np.asarray(p_values, dtype=np.float64).ravel()
    n = int(p.size)
    if n == 0:
        return p.copy()

    order = np.argsort(p, kind="mergesort")
    ranked = p[order]
    q = ranked * float(n) / np.arange(1, n + 1, dtype=np.float64)
    # 自右向左取累计最小值，保证 q 随 p 单调不减
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0.0, 1.0)

    out = np.empty(n, dtype=np.float64)
    out[order] = q
    return out


class NullCalibrator:
    """
    药物级随机签名 null 校准器。

    Args:
        drug_mat: shape=(G, n_drug) 的药物 × landmark 中位数矩阵（float32；
            可以是 np.load(..., mmap_mode='r') 的只读 memmap）
        drug_names: 长度 n_drug 的药物名列表，顺序与矩阵列一致
        lm_gene_ids: 长度 G 的 landmark 基因 ID 列表，顺序与矩阵行一致
        n_null: 随机签名个数 M（默认 10000）
        seed: RNG 种子（默认 0）；相同 seed/查询可复现
        batch_size: 每批随机签名数（默认 500，不会构造 (M, n_drug)）
        min_genes: up+down 的 landmark 基因数下限（默认 10）
    """

    def __init__(
        self,
        drug_mat,
        drug_names: List[str],
        lm_gene_ids: List[int],
        n_null: int = 10000,
        seed: int = 0,
        batch_size: int = 500,
        min_genes: int = 10,
    ):
        if getattr(drug_mat, "ndim", None) != 2:
            raise ValueError("drug_mat 必须是二维矩阵")
        if len(drug_names) != int(drug_mat.shape[1]):
            raise ValueError(
                "drug_names 数量 {} 与矩阵列数 {} 不一致".format(
                    len(drug_names), drug_mat.shape[1]
                )
            )
        if len(lm_gene_ids) != int(drug_mat.shape[0]):
            raise ValueError(
                "lm_gene_ids 数量 {} 与矩阵行数 {} 不一致".format(
                    len(lm_gene_ids), drug_mat.shape[0]
                )
            )
        if int(n_null) <= 0:
            raise ValueError("n_null 必须为正整数")
        if int(batch_size) <= 0:
            raise ValueError("batch_size 必须为正整数")
        if int(min_genes) < 0:
            raise ValueError("min_genes 不能为负")

        self.drug_mat = drug_mat
        self.drug_names = [str(x) for x in drug_names]
        self.lm_gene_ids = list(lm_gene_ids)
        self.n_null = int(n_null)
        self.seed = int(seed)
        self.batch_size = int(batch_size)
        self.min_genes = int(min_genes)

        self._gene_to_row = {
            str(gid): i for i, gid in enumerate(self.lm_gene_ids)
        }
        self.last_status = STATUS_UNAVAILABLE

    # ------------------------------------------------------------------
    # 基因映射
    # ------------------------------------------------------------------

    def _gene_rows(self, gene_ids) -> List[int]:
        """把查询基因 ID 映射为 landmark 行号（去重、保持顺序、忽略非 landmark）。"""
        rows = []
        seen = set()
        for gid in gene_ids or []:
            row = self._gene_to_row.get(str(gid))
            if row is not None and row not in seen:
                seen.add(row)
                rows.append(row)
        return rows

    def _empty_result(self, status: str) -> pd.DataFrame:
        self.last_status = status
        df = pd.DataFrame(columns=RESULT_COLUMNS)
        df.attrs["null_calibration"] = status
        return df

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def calibrate(self, up_gene_ids: List[int], down_gene_ids: List[int]) -> pd.DataFrame:
        """
        对全部药物计算 xsum、经验 p 值、BH-FDR 与 null z。

        Returns:
            DataFrame[pert_iname, xsum, p_reversal, fdr_reversal, null_z]
            若 up+down 落在 landmark 内的基因 < min_genes，返回空表，并把
            last_status / df.attrs["null_calibration"] 置为
            "insufficient_landmark_genes"；成功时为 "ok"。
        """
        up_rows = self._gene_rows(up_gene_ids)
        down_rows = self._gene_rows(down_gene_ids)

        # 同一基因同时出现在 up 与 down：两侧都去掉，避免观测值重复计数
        # （随机签名是无放回抽样，不会把同一基因抽两次）。
        overlap = set(up_rows) & set(down_rows)
        if overlap:
            up_rows = [r for r in up_rows if r not in overlap]
            down_rows = [r for r in down_rows if r not in overlap]

        if len(up_rows) + len(down_rows) < self.min_genes:
            return self._empty_result(STATUS_INSUFFICIENT)

        n_up = len(up_rows)
        n_down = len(down_rows)
        n_sample = n_up + n_down
        G = int(self.drug_mat.shape[0])
        n_drug = int(self.drug_mat.shape[1])
        if n_sample > G:
            raise ValueError(
                "随机签名大小 {} 超过 landmark 基因数 {}".format(n_sample, G)
            )

        # 1) 观测 xsum：Σz(up) − Σz(down)，负 = 逆转
        obs = np.zeros(n_drug, dtype=np.float64)
        if n_up:
            obs += np.asarray(
                self.drug_mat[np.asarray(up_rows, dtype=np.int64)].sum(axis=0),
                dtype=np.float64,
            ).ravel()
        if n_down:
            obs -= np.asarray(
                self.drug_mat[np.asarray(down_rows, dtype=np.int64)].sum(axis=0),
                dtype=np.float64,
            ).ravel()
        # 与 float32 的 null 比较时保持同 dtype，避免每批生成 float64 临时数组
        obs_cmp = obs.astype(np.float32)

        # 2) 分批随机签名 null。只保留累计计数/矩，不构造 (M, n_drug)。
        le = np.zeros(n_drug, dtype=np.int64)       # null <= obs（下尾 = 逆转）
        sum_null = np.zeros(n_drug, dtype=np.float64)
        sum_sq = np.zeros(n_drug, dtype=np.float64)
        rng = np.random.default_rng(self.seed)

        M = self.n_null
        batch_size = min(self.batch_size, M)
        done = 0
        while done < M:
            b = min(batch_size, M - done)

            # 每行独立无放回抽样：random + argpartition，避免 Python 循环
            keys = rng.random((b, G))
            chosen = np.argpartition(keys, n_sample - 1, axis=1)[:, :n_sample]

            # 权重：up 记 +1、down 记 −1 → W @ drug_mat 就是 null xsum
            W = np.zeros((b, G), dtype=np.float32)
            if n_up:
                W[np.repeat(np.arange(b), n_up), chosen[:, :n_up].ravel()] = 1.0
            if n_down:
                W[np.repeat(np.arange(b), n_down), chosen[:, n_up:].ravel()] = -1.0

            null = np.asarray(W @ self.drug_mat, dtype=np.float32)
            del W, keys, chosen

            le += np.count_nonzero(null <= obs_cmp, axis=0)
            sum_null += null.sum(axis=0, dtype=np.float64)
            sum_sq += np.einsum("ij,ij->j", null, null, dtype=np.float64)
            del null
            done += b

        # 3) 经验 p 值（单侧下尾）
        denom = float(M + 1)
        p_reversal = (le.astype(np.float64) + 1.0) / denom
        fdr_reversal = benjamini_hochberg(p_reversal)

        # 4) null z：负 = 观测比随机更逆转
        null_mean = sum_null / float(M)
        null_var = np.maximum(sum_sq / float(M) - null_mean ** 2, 0.0)
        null_sd = np.sqrt(null_var)
        null_z = np.zeros(n_drug, dtype=np.float64)
        np.divide(obs - null_mean, null_sd, out=null_z, where=null_sd > 0)

        self.last_status = STATUS_OK
        df = pd.DataFrame(
            {
                "pert_iname": self.drug_names,
                "xsum": obs,
                "p_reversal": p_reversal,
                "fdr_reversal": fdr_reversal,
                "null_z": null_z,
            }
        )
        df.attrs["null_calibration"] = STATUS_OK
        return df


# ----------------------------------------------------------------------
# 进程内单例（矩阵 mmap）
# ----------------------------------------------------------------------

_instance = None  # type: Optional[NullCalibrator]


def _load_names(path: str) -> List[str]:
    df = pd.read_csv(path)
    for col in ("pert_iname", "drug_name"):
        if col in df.columns:
            return [str(x) for x in df[col].tolist()]
    if df.shape[1] == 0:
        raise ValueError("药名文件没有列: {}".format(path))
    return [str(x) for x in df.iloc[:, 0].tolist()]


def _load_gene_ids(path: str) -> List[int]:
    df = pd.read_csv(path)
    for col in ("gene_id", "pr_gene_id"):
        if col in df.columns:
            return [int(x) for x in df[col].tolist()]
    raise ValueError("landmark 基因文件缺少 gene_id 列: {}".format(path))


def _paths_exist() -> bool:
    return all(
        os.path.exists(p)
        for p in (
            DRUG_MEDIAN_MATRIX_PATH,
            DRUG_MEDIAN_NAMES_PATH,
            DRUG_MEDIAN_GENE_IDS_PATH,
        )
    )


def get_null_calibrator() -> Optional[NullCalibrator]:
    """
    获取进程内单例；矩阵/药名/基因文件缺失或读取失败时返回 None。

    每次调用都检查文件是否存在：部署时删除/替换矩阵后无需重启即可生效
    （已加载的 mmap 在 Windows 上可能仍持有文件句柄，此时应先调用
    reset_null_calibrator() 再删除）。
    """
    global _instance
    if not _paths_exist():
        _instance = None
        return None
    if _instance is None:
        try:
            drug_mat = np.load(DRUG_MEDIAN_MATRIX_PATH, mmap_mode="r")
            names = _load_names(DRUG_MEDIAN_NAMES_PATH)
            gene_ids = _load_gene_ids(DRUG_MEDIAN_GENE_IDS_PATH)
            _instance = NullCalibrator(
                drug_mat,
                names,
                gene_ids,
                n_null=NULL_CALIBRATION_N,
                seed=NULL_CALIBRATION_SEED,
                batch_size=NULL_CALIBRATION_BATCH,
                min_genes=NULL_CALIBRATION_MIN_GENES,
            )
            print(
                "[NullCalibrator] 已加载药物中位数矩阵: {} × {}".format(
                    drug_mat.shape[0], drug_mat.shape[1]
                )
            )
        except Exception as exc:  # 矩阵损坏时也不要让 Tau 搜索失败
            print("[NullCalibrator] 加载失败，跳过 null 校准: {}".format(exc))
            _instance = None
            return None
    return _instance


def reset_null_calibrator():
    """释放单例（主要供测试/部署替换矩阵时使用）。"""
    global _instance
    _instance = None
    gc.collect()
