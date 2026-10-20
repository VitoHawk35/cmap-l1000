#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D1 · cmap 数据完整性防线测试（防线1 接入 metadata_index / matrix_store）。

覆盖：
- 正确数据：MetadataIndex / MatrixStore 正常加载（默认 fingerprint 模式）；
- 列花名册：换成另一版本顺序 / 随机打乱 / 只错 1 位 → MetadataIndex 拒绝加载；
- 行花名册：随机打乱 / 少一行 → MatrixStore 拒绝加载；
- 矩阵被换成同形状的另一个文件 → MatrixStore 拒绝加载；
- LINCS_INTEGRITY_MODE=off → 放行但打 WARNING（仅供测试）。

注意：app 模块必须在 fixture 内懒加载——app.config 在 import 时读取
CMAP_* 环境变量，模块级 import 会在 conftest 设置环境变量之前缓存配置。
"""

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from make_synthetic_data import make_synthetic_data


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """独立的合成数据集（含 integrity.json）+ 被 monkeypatch 到该数据目录的模块。

    不污染 session 级单例；结束时复位 MetadataIndex / MatrixStore 单例。
    """
    d = tmp_path / "cmap_data"
    info = make_synthetic_data(str(d))

    # 若这是本次会话首次 import app.*，config 会读取下面的环境变量；
    # 之后无论 config 绑定到哪个目录，都用模块级 monkeypatch 覆盖本测试的路径。
    monkeypatch.setenv("CMAP_DATA_DIR", str(d))
    monkeypatch.setenv("CMAP_N_GENES", str(info["n_genes"]))
    monkeypatch.setenv("CMAP_N_SIGS", str(info["n_sigs"]))
    monkeypatch.setenv("CMAP_TEMP_DIR", str(tmp_path / "cmap_temp"))

    from app.core import matrix_store as ms_mod
    from app.core import metadata_index as mi_mod
    from app.core.matrix_store import MatrixStore
    from app.core.metadata_index import MetadataIndex

    for mod in (mi_mod, ms_mod):
        monkeypatch.setattr(mod, "MATRIX_PATH", os.path.join(str(d), "fast_matrix.npy"))
        monkeypatch.setattr(mod, "COL_NAMES_PATH", os.path.join(str(d), "col_sig_ids.csv"))
        monkeypatch.setattr(mod, "ROW_NAMES_PATH", os.path.join(str(d), "row_gene_ids.csv"))
    monkeypatch.setattr(
        mi_mod, "SIG_INFO_PATH",
        os.path.join(str(d), "GSE92742_Broad_LINCS_sig_info.txt.gz"),
    )
    monkeypatch.setattr(mi_mod, "N_SIGS", info["n_sigs"])
    monkeypatch.setattr(ms_mod, "N_GENES", info["n_genes"])
    monkeypatch.setattr(ms_mod, "N_SIGS", info["n_sigs"])

    MetadataIndex._instance = None
    MatrixStore._instance = None

    yield SimpleNamespace(
        info=info,
        data_dir=str(d),
        mi=mi_mod,
        ms=ms_mod,
        MetadataIndex=MetadataIndex,
        MatrixStore=MatrixStore,
    )

    MetadataIndex._instance = None
    MatrixStore._instance = None
    ms_mod.MatrixStore._matrix = None


def _rewrite_col_roster(env, sig_ids):
    pd.DataFrame({"sig_id": sig_ids}).to_csv(
        os.path.join(env.data_dir, "col_sig_ids.csv"), index=False
    )


def _rewrite_row_roster(env, gene_ids):
    pd.DataFrame({"gene_id": gene_ids}).to_csv(
        os.path.join(env.data_dir, "row_gene_ids.csv"), index=False
    )


def _col_ids(env):
    return pd.read_csv(
        os.path.join(env.data_dir, "col_sig_ids.csv")
    )["sig_id"].astype(str).tolist()


def _row_ids(env):
    return pd.read_csv(
        os.path.join(env.data_dir, "row_gene_ids.csv")
    )["gene_id"].astype(str).tolist()


# ---------------------------------------------------------------------------
# 正确数据
# ---------------------------------------------------------------------------

def test_correct_data_loads(env):
    idx = env.MetadataIndex()
    assert len(idx._sig_to_idx) == env.info["n_sigs"]
    store = env.MatrixStore()
    assert store.shape == (env.info["n_genes"], env.info["n_sigs"])


# ---------------------------------------------------------------------------
# 列花名册破坏 → MetadataIndex 拒绝加载
# ---------------------------------------------------------------------------

def test_col_roster_other_version_rejected(env):
    """列花名册被换成另一个版本（集合相同、顺序不同，这里用逆字典序）→ 拒绝。"""
    # 合成数据的 sig_id 恰好按字典序生成，sorted() 为恒等，故用逆序确保顺序变化
    _rewrite_col_roster(env, sorted(_col_ids(env), reverse=True))
    with pytest.raises(RuntimeError, match="col_sig_ids.csv"):
        env.MetadataIndex()


def test_col_roster_shuffled_rejected(env):
    ids = _col_ids(env)
    perm = np.random.RandomState(7).permutation(len(ids))
    _rewrite_col_roster(env, [ids[i] for i in perm])
    with pytest.raises(RuntimeError, match="col_sig_ids.csv"):
        env.MetadataIndex()


def test_col_roster_one_off_rejected(env):
    ids = _col_ids(env)
    ids[11] = "SIG_TAMPERED_000"
    _rewrite_col_roster(env, ids)
    with pytest.raises(RuntimeError, match="col_sig_ids.csv"):
        env.MetadataIndex()


# ---------------------------------------------------------------------------
# 行花名册破坏 → MatrixStore 拒绝加载
# ---------------------------------------------------------------------------

def test_row_roster_shuffled_rejected(env):
    ids = _row_ids(env)
    perm = np.random.RandomState(3).permutation(len(ids))
    _rewrite_row_roster(env, [ids[i] for i in perm])
    with pytest.raises(RuntimeError, match="row_gene_ids.csv"):
        env.MatrixStore()


def test_row_roster_missing_line_rejected(env):
    _rewrite_row_roster(env, _row_ids(env)[:-1])
    with pytest.raises(RuntimeError, match="row_gene_ids.csv"):
        env.MatrixStore()


# ---------------------------------------------------------------------------
# 矩阵被换成同形状的另一个文件 → MatrixStore 拒绝加载
# ---------------------------------------------------------------------------

def test_matrix_swap_same_shape_rejected(env):
    rng = np.random.RandomState(999)
    evil = rng.standard_normal(
        (env.info["n_genes"], env.info["n_sigs"])
    ).astype(np.float32)
    np.ascontiguousarray(evil).tofile(os.path.join(env.data_dir, "fast_matrix.npy"))
    with pytest.raises(RuntimeError, match="矩阵"):
        env.MatrixStore()


# ---------------------------------------------------------------------------
# off 模式：放行但必须 WARNING
# ---------------------------------------------------------------------------

def test_off_mode_passes_with_warning(env, monkeypatch, caplog):
    ids = _col_ids(env)
    perm = np.random.RandomState(7).permutation(len(ids))
    _rewrite_col_roster(env, [ids[i] for i in perm])
    monkeypatch.setenv("LINCS_INTEGRITY_MODE", "off")

    with caplog.at_level("WARNING", logger="lincs_integrity"):
        idx = env.MetadataIndex()
    assert len(idx._sig_to_idx) == env.info["n_sigs"]
    assert any(
        r.levelname == "WARNING" and "仅供测试" in r.getMessage()
        for r in caplog.records
    )
