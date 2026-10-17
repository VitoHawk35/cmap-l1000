#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C3：scripts/build_drug_median.py 单测。

覆盖：
1. 只取 pert_type == 'trt_cp'；
2. 只保留 gene_info 中 pr_is_lm == 1 的行；
3. 按 pert_iname 分组取中位数，药名排序稳定；
4. 分块大小不影响结果；
5. --from-lmna 复用 LMNA 的 .npy + 药名 CSV。
"""

import os

import numpy as np
import pandas as pd
import pytest


N_GENES = 12
N_LANDMARK = 10


def _write_raw_matrix(path, values):
    """values shape=(n_genes, n_sigs)，写成裸 float32 memmap（无 .npy 头）。"""
    mat = np.memmap(path, dtype="float32", mode="w+", shape=values.shape)
    mat[:] = values
    mat.flush()
    del mat


def _make_tiny_dataset(data_dir):
    """3 个 trt_cp 药 + 1 个 trt_sh 药；后 2 个基因非 landmark。"""
    os.makedirs(data_dir, exist_ok=True)
    gene_ids = [101 + i for i in range(N_GENES)]
    sig_ids = ["SIG0", "SIG1", "SIG2", "SIG3", "SIG4", "SIG5"]

    values = np.zeros((N_GENES, len(sig_ids)), dtype=np.float32)
    # landmark 行：drugA (SIG0-2) 中位数 = 2；drugB = 10；drugD = 5
    values[:N_LANDMARK, 0] = 1.0
    values[:N_LANDMARK, 1] = 2.0
    values[:N_LANDMARK, 2] = 3.0
    values[:N_LANDMARK, 3] = 10.0
    values[:N_LANDMARK, 4] = 999.0   # trt_sh，应被排除
    values[:N_LANDMARK, 5] = 5.0
    # 非 landmark 行：若误用会得到很大的值
    values[N_LANDMARK:, 0] = 100.0
    values[N_LANDMARK:, 1] = 200.0
    values[N_LANDMARK:, 2] = 300.0
    values[N_LANDMARK:, 3:] = 1000.0

    _write_raw_matrix(os.path.join(data_dir, "fast_matrix.npy"), values)
    pd.DataFrame({"gene_id": gene_ids}).to_csv(
        os.path.join(data_dir, "row_gene_ids.csv"), index=False
    )
    pd.DataFrame({"sig_id": sig_ids}).to_csv(
        os.path.join(data_dir, "col_sig_ids.csv"), index=False
    )

    sig_info = pd.DataFrame(
        {
            "sig_id": sig_ids,
            "pert_id": ["P0", "P0", "P0", "P1", "P2", "P3"],
            "pert_iname": ["drugA", "drugA", "drugA", "drugB", "drugC", "drugD"],
            "cell_id": ["A375"] * len(sig_ids),
            "pert_idose": ["1 uM"] * len(sig_ids),
            "pert_type": ["trt_cp", "trt_cp", "trt_cp", "trt_cp", "trt_sh", "trt_cp"],
        }
    )
    sig_info.to_csv(
        os.path.join(data_dir, "GSE92742_Broad_LINCS_sig_info.txt.gz"),
        sep="\t",
        compression="gzip",
        index=False,
    )

    gene_info = pd.DataFrame(
        {
            "pr_gene_id": gene_ids,
            "pr_gene_symbol": ["G{}".format(g) for g in gene_ids],
            "pr_is_lm": [1] * N_LANDMARK + [0] * (N_GENES - N_LANDMARK),
        }
    )
    gene_info.to_csv(
        os.path.join(data_dir, "GSE92742_Broad_LINCS_gene_info.txt.gz"),
        sep="\t",
        compression="gzip",
        index=False,
    )
    return gene_ids


def _load_outputs(result):
    mat = np.load(result["matrix_path"])
    names = pd.read_csv(result["names_path"])["pert_iname"].tolist()
    genes = pd.read_csv(result["gene_ids_path"])["gene_id"].tolist()
    return mat, names, genes


def test_build_filters_trt_cp_and_landmark(tmp_path):
    from scripts.build_drug_median import build_drug_median

    data_dir = str(tmp_path)
    gene_ids = _make_tiny_dataset(data_dir)
    result = build_drug_median(data_dir)
    mat, names, genes = _load_outputs(result)

    # 只保留 3 个 trt_cp 药，按名称排序；trt_sh 的 drugC 被排除
    assert names == ["drugA", "drugB", "drugD"]
    # 只保留 10 个 landmark 行（非 landmark 行会造成 200/1000 的异常值）
    assert mat.shape == (N_LANDMARK, 3)
    assert mat.dtype == np.float32
    assert genes == gene_ids[:N_LANDMARK]
    assert np.allclose(mat[:, 0], 2.0)
    assert np.allclose(mat[:, 1], 10.0)
    assert np.allclose(mat[:, 2], 5.0)


def test_build_chunk_size_does_not_change_result(tmp_path):
    from scripts.build_drug_median import build_drug_median

    _make_tiny_dataset(str(tmp_path))
    a = build_drug_median(str(tmp_path), chunk_size=1)
    mat_a = np.load(a["matrix_path"])
    b = build_drug_median(str(tmp_path), chunk_size=1000)
    mat_b = np.load(b["matrix_path"])
    assert np.array_equal(mat_a, mat_b)


def test_import_from_lmna(tmp_path):
    from scripts.build_drug_median import import_from_lmna

    data_dir = str(tmp_path / "cmap")
    lmna_dir = str(tmp_path / "lmna_cache")
    os.makedirs(lmna_dir)
    gene_ids = _make_tiny_dataset(data_dir)

    src = np.arange(N_LANDMARK * 3, dtype=np.float32).reshape(N_LANDMARK, 3)
    np.save(os.path.join(lmna_dir, "_drug_median_matrix.v2.npy"), src)
    pd.DataFrame({"drug_name": ["A", "B", "C"]}).to_csv(
        os.path.join(lmna_dir, "_drug_names.v2.csv"), index=False
    )

    result = import_from_lmna(lmna_dir, data_dir)
    mat, names, genes = _load_outputs(result)

    assert names == ["A", "B", "C"]
    assert genes == gene_ids[:N_LANDMARK]
    assert np.array_equal(mat, src)


def test_import_from_lmna_row_mismatch_raises(tmp_path):
    from scripts.build_drug_median import import_from_lmna

    data_dir = str(tmp_path / "cmap")
    lmna_dir = str(tmp_path / "lmna_cache")
    os.makedirs(lmna_dir)
    _make_tiny_dataset(data_dir)

    # 行数不是 10（与本地 landmark 数不一致）
    np.save(
        os.path.join(lmna_dir, "_drug_median_matrix.npy"),
        np.zeros((5, 2), dtype=np.float32),
    )
    pd.DataFrame({"drug_name": ["A", "B"]}).to_csv(
        os.path.join(lmna_dir, "_drug_names.csv"), index=False
    )
    with pytest.raises(ValueError):
        import_from_lmna(lmna_dir, data_dir)


def test_build_on_synthetic_dataset(drug_median_data, synthetic_data):
    """合成 978 行风格数据集：形状正确，逆转药中位数方向正确。"""
    mat, names, genes = _load_outputs(drug_median_data)
    assert mat.shape == (
        len(synthetic_data["gene_ids"]), len(names)
    )
    assert mat.dtype == np.float32
    assert genes == list(synthetic_data["gene_ids"])

    j = names.index(synthetic_data["reversal_drug"])
    up_rows = [genes.index(g) for g in synthetic_data["up_gene_ids"]]
    down_rows = [genes.index(g) for g in synthetic_data["down_gene_ids"]]
    assert np.allclose(mat[up_rows, j], -3.0, atol=0.2)
    assert np.allclose(mat[down_rows, j], 3.0, atol=0.2)
