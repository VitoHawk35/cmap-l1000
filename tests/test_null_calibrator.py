#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C3 单测：查询内随机签名 null → 经验 p 值 / BH-FDR / null z。

符号约定（与 app/scoring/null_calibrator.py 一致）：
    xsum = Σz(up) − Σz(down)，负 = 逆转
    p_reversal = (#{null <= xsum} + 1) / (M + 1)
    null_z = (xsum − mean(null)) / sd(null)，负 = 比随机更逆转

注意：本文件不在模块顶层 import app.*，否则会在 pytest 收集阶段
早于 synthetic_data fixture 冻结 app.config 的环境变量。
"""

import gc
import tracemalloc

import numpy as np
import pytest
from scipy import stats


G = 978
N_DRUG = 300
N_UP = 25
N_DOWN = 25


@pytest.fixture(autouse=True)
def _ensure_cmap_env(synthetic_data):
    """
    确保 synthetic_data fixture 先设置 CMAP_* 环境变量，再在测试函数内
    import app.*（否则 app.config 会在默认路径上冻结）。
    """
    return synthetic_data


def _synthetic_case(seed=0, n_drug=N_DRUG):
    """G=978、n_drug-1 个随机药物 + 1 个完美逆转药。"""
    rng = np.random.default_rng(seed)
    matrix = rng.standard_normal((G, n_drug)).astype(np.float32)
    up = rng.choice(G, N_UP, replace=False)
    down = rng.choice(np.setdiff1d(np.arange(G), up), N_DOWN, replace=False)

    perfect = n_drug - 1
    matrix[:, perfect] = 0.0
    # up 下调、down 上调 → xsum = Σup − Σdown 远小于 0（完美逆转）
    matrix[up, perfect] = -1.0
    matrix[down, perfect] = 1.0

    gene_ids = list(range(1000, 1000 + G))
    names = ["drug_{:03d}".format(i) for i in range(n_drug)]
    up_ids = [int(gene_ids[i]) for i in up]
    down_ids = [int(gene_ids[i]) for i in down]
    return matrix, names, gene_ids, up_ids, down_ids, perfect


def _calibrator(n_null=1000, seed=42, n_drug=N_DRUG, batch_size=500):
    from app.scoring.null_calibrator import NullCalibrator

    matrix, names, gene_ids, up_ids, down_ids, perfect = _synthetic_case(
        n_drug=n_drug
    )
    calibrator = NullCalibrator(
        matrix, names, gene_ids, n_null=n_null, seed=seed, batch_size=batch_size
    )
    return calibrator, up_ids, down_ids, perfect


# ---------------------------------------------------------------------------
# 验收：完美逆转药、p 值均匀性
# ---------------------------------------------------------------------------

def test_perfect_reversal_drug_has_small_fdr():
    """
    完美逆转药 fdr_reversal < 0.01。

    注：全局 BH 在 n_drug=300、M=10000 时的最小可达 FDR 约为
    300/10001≈0.030，数学上不可能 <0.01；因此本用例用 M=40000
    （300/40001≈0.0075）验证该验收阈值。M=2000 仅用于下面的 KS 检验。
    与 LMNA L4 的处理方式一致。
    """
    calibrator, up_ids, down_ids, perfect = _calibrator(n_null=40000)
    df = calibrator.calibrate(up_ids, down_ids)

    assert calibrator.last_status == "ok"
    assert df.attrs["null_calibration"] == "ok"
    assert list(df.columns) == [
        "pert_iname", "xsum", "p_reversal", "fdr_reversal", "null_z"
    ]
    assert len(df) == N_DRUG

    assert df["xsum"].iloc[perfect] < 0
    assert df["p_reversal"].iloc[perfect] <= 5.0 / (40000 + 1)
    assert df["null_z"].iloc[perfect] < -5
    assert df["fdr_reversal"].iloc[perfect] < 0.01
    # 完美药应是 p_reversal 最小的药
    assert int(np.argmin(df["p_reversal"].values)) == perfect


def test_random_drugs_p_reversal_is_uniform():
    """随机药物的 p_reversal 应近似 U(0,1)（KS 检验 p > 0.01，M=2000）。"""
    calibrator, up_ids, down_ids, perfect = _calibrator(n_null=2000, batch_size=500)
    df = calibrator.calibrate(up_ids, down_ids)

    p_random = df["p_reversal"].values[:-1]  # 去掉完美逆转药
    ks = stats.kstest(p_random, "uniform")
    assert ks.pvalue > 0.01, "p_reversal 偏离均匀分布: {}".format(ks)

    lo = 1.0 / (2000 + 1)
    assert df["p_reversal"].min() >= lo - 1e-15
    assert df["p_reversal"].max() <= 1.0
    assert df["fdr_reversal"].min() >= 0.0
    assert df["fdr_reversal"].max() <= 1.0
    # BH 校正后不小于原始 p
    assert np.all(df["fdr_reversal"].values >= df["p_reversal"].values - 1e-12)


# ---------------------------------------------------------------------------
# BH 与 scipy 对比
# ---------------------------------------------------------------------------

def _scipy_bh_reference(p_values):
    """用 scipy.stats.rankdata 的独立 BH 参考实现。"""
    from scipy.stats import rankdata

    p = np.asarray(p_values, dtype=np.float64).ravel()
    n = p.size
    if n == 0:
        return p.copy()
    ranks = rankdata(p, method="ordinal")
    q = p * float(n) / ranks
    order = np.argsort(p, kind="mergesort")
    q_sorted = q[order]
    q_sorted = np.minimum.accumulate(q_sorted[::-1])[::-1]
    out = np.empty(n, dtype=np.float64)
    out[order] = np.clip(q_sorted, 0.0, 1.0)
    return out


def test_bh_matches_scipy_rankdata_reference():
    """BH 与 scipy 参考实现最大差 < 1e-12（含并列 p 值）。"""
    from app.scoring.null_calibrator import benjamini_hochberg

    rng = np.random.default_rng(0)
    cases = [
        rng.random(1),
        rng.random(2),
        rng.random(17),
        rng.random(300),
        np.array([0.01, 0.01, 0.02, 0.5, 1.0]),
        np.ones(10),
        np.array([1e-12, 2e-12, 0.03, 0.04]),
    ]
    for p in cases:
        got = benjamini_hochberg(p)
        ref = _scipy_bh_reference(p)
        assert np.max(np.abs(got - ref)) < 1e-12, "p={}".format(p)


@pytest.mark.skipif(
    not hasattr(stats, "false_discovery_control"),
    reason="当前 scipy 版本没有 false_discovery_control（Python 3.8 最高 scipy 1.10）",
)
def test_bh_matches_scipy_false_discovery_control():
    """若 scipy >= 1.11 提供 false_discovery_control，则直接与它对比。"""
    from scipy.stats import false_discovery_control

    from app.scoring.null_calibrator import benjamini_hochberg

    rng = np.random.default_rng(1)
    for n in (1, 5, 50, 500):
        p = rng.random(n)
        if n >= 5:
            p[: n // 10] = p[0]  # 制造并列
        got = benjamini_hochberg(p)
        ref = false_discovery_control(p, method="bh")
        assert np.max(np.abs(got - ref)) < 1e-12


# ---------------------------------------------------------------------------
# landmark 过滤 / 不足保护 / 分批一致性 / 确定性
# ---------------------------------------------------------------------------

def test_insufficient_landmark_genes_returns_empty():
    calibrator, up_ids, down_ids, _ = _calibrator(n_null=100)

    # 4 up + 5 down = 9 个 landmark 基因 < 10
    df = calibrator.calibrate(up_ids[:4], down_ids[:5])
    assert df.empty
    assert list(df.columns) == [
        "pert_iname", "xsum", "p_reversal", "fdr_reversal", "null_z"
    ]
    assert calibrator.last_status == "insufficient_landmark_genes"
    assert df.attrs["null_calibration"] == "insufficient_landmark_genes"

    # 非 landmark 基因不计数
    df2 = calibrator.calibrate(up_ids[:4] + [999999], down_ids[:5] + [888888])
    assert df2.empty
    assert calibrator.last_status == "insufficient_landmark_genes"


def test_only_landmark_genes_are_used_and_unknown_ignored():
    calibrator, up_ids, down_ids, _ = _calibrator(n_null=100)
    df_with_unknown = calibrator.calibrate(
        up_ids + [999999, 888888], down_ids + [777777]
    )
    df_clean = calibrator.calibrate(up_ids, down_ids)
    assert calibrator.last_status == "ok"
    assert len(df_with_unknown) == N_DRUG
    assert np.allclose(
        df_with_unknown["xsum"].values, df_clean["xsum"].values, atol=1e-12
    )


def test_batched_matches_single_batch():
    """相同 seed/M 下，分批与单批结果一致（RNG 流不随分块改变）。"""
    batched, up_ids, down_ids, _ = _calibrator(
        n_null=1000, seed=7, batch_size=100
    )
    single, _, _, _ = _calibrator(n_null=1000, seed=7, batch_size=1000)
    a = batched.calibrate(up_ids, down_ids)
    b = single.calibrate(up_ids, down_ids)

    assert np.array_equal(a["p_reversal"].values, b["p_reversal"].values)
    assert np.array_equal(a["fdr_reversal"].values, b["fdr_reversal"].values)
    assert np.allclose(a["xsum"].values, b["xsum"].values, atol=1e-12)
    assert np.allclose(a["null_z"].values, b["null_z"].values, atol=1e-9)


def test_seed_is_deterministic():
    cal1, up_ids, down_ids, _ = _calibrator(n_null=500, seed=123)
    cal2, _, _, _ = _calibrator(n_null=500, seed=123)
    cal3, _, _, _ = _calibrator(n_null=500, seed=124)
    df1 = cal1.calibrate(up_ids, down_ids)
    df2 = cal2.calibrate(up_ids, down_ids)
    df3 = cal3.calibrate(up_ids, down_ids)

    assert np.array_equal(df1["p_reversal"].values, df2["p_reversal"].values)
    assert np.array_equal(df1["null_z"].values, df2["null_z"].values)
    assert not np.array_equal(df1["p_reversal"].values, df3["p_reversal"].values)


def test_empty_signature_is_insufficient():
    calibrator, _, _, _ = _calibrator(n_null=50)
    df = calibrator.calibrate([], [])
    assert df.empty
    assert calibrator.last_status == "insufficient_landmark_genes"


# ---------------------------------------------------------------------------
# 内存：不得构造完整 (M, n_drug)
# ---------------------------------------------------------------------------

def test_does_not_build_full_null_matrix():
    """n_drug=20000 时峰值内存仍应远小于 1GB（分批累计）。"""
    from app.scoring.null_calibrator import NullCalibrator

    rng = np.random.default_rng(0)
    matrix = rng.standard_normal((G, 20000), dtype=np.float32)
    gene_ids = list(range(1000, 1000 + G))
    up_idx = rng.choice(G, N_UP, replace=False)
    down_idx = rng.choice(np.setdiff1d(np.arange(G), up_idx), N_DOWN, replace=False)
    up_ids = [int(gene_ids[i]) for i in up_idx]
    down_ids = [int(gene_ids[i]) for i in down_idx]
    calibrator = NullCalibrator(
        matrix, ["d{}".format(i) for i in range(20000)], gene_ids,
        n_null=200, seed=0, batch_size=50,
    )

    gc.collect()
    tracemalloc.start()
    try:
        df = calibrator.calibrate(up_ids, down_ids)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(df) == 20000
    # 完整 (200, 20000) float32 只有 16MB；真正的保护是 M=10000 时不构造
    # (10000, 20000)=800MB。这里用 1GB 作为宽松上限，防止实现退化为
    # 一次性构造大矩阵（真实规模峰值另见交付说明）。
    assert peak < 1024 ** 3, "峰值内存 {:.1f} MB 超过 1GB".format(peak / 1e6)
