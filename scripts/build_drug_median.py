#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
构建"药物 × landmark 基因"中位数矩阵（C3 方案 B 的数据前提）。

流程：
1. 读 sig_info，取 pert_type == 'trt_cp' 的签名；
2. 按 pert_iname 分组；
3. 对 gene_info 中 pr_is_lm == 1 的 landmark 行，取每个药所有签名的中位数；
4. 保存到 DATA_DIR：
   - drug_median_lm.npy            (978 × n_drug, float32, 标准 .npy)
   - drug_median_names.csv         (列 pert_iname)
   - drug_median_lm_gene_ids.csv   (列 gene_id，行顺序与矩阵一致)

也支持直接复用 LMNA 已生成的药物中位数矩阵：
    python scripts/build_drug_median.py --from-lmna ~/lmna_v2_cache

LMNA 文件名兼容 `_drug_median_matrix.v2.npy` / `_drug_names.v2.csv`
（无版本后缀的旧文件名也兼容；实际数据在服务器 ~/lmna_v2_cache/ 下）。

注意：fast_matrix.npy 是**裸 float32 memmap（无 .npy 文件头）**，
必须用 np.memmap(..., shape=(n_genes, n_sigs)) 打开，不能 np.load。
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# 允许 `python scripts/build_drug_median.py` 直接运行（脚本目录不在 repo 根）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def _default_data_dir() -> str:
    """惰性读取 app.config.DATA_DIR，避免 import 脚本时过早冻结环境变量。"""
    try:
        from app.config import DATA_DIR

        return DATA_DIR
    except Exception:
        return os.getenv("CMAP_DATA_DIR", os.path.join(PROJECT_ROOT, "cmap_data"))


MATRIX_FILENAME = "drug_median_lm.npy"
NAMES_FILENAME = "drug_median_names.csv"
GENE_IDS_FILENAME = "drug_median_lm_gene_ids.csv"


def _default_paths(data_dir: str) -> Tuple[str, str, str, str, str]:
    """返回 (sig_info, gene_info, matrix, row_names, col_names) 默认路径。"""
    return (
        os.path.join(data_dir, "GSE92742_Broad_LINCS_sig_info.txt.gz"),
        os.path.join(data_dir, "GSE92742_Broad_LINCS_gene_info.txt.gz"),
        os.path.join(data_dir, "fast_matrix.npy"),
        os.path.join(data_dir, "row_gene_ids.csv"),
        os.path.join(data_dir, "col_sig_ids.csv"),
    )


def load_landmark_gene_ids(gene_info_path: str) -> List[int]:
    """按 gene_info 文件顺序返回 pr_is_lm == 1 的基因 ID（LMNA 矩阵行序一致）。"""
    gene_info = pd.read_csv(
        gene_info_path, sep="\t", usecols=["pr_gene_id", "pr_is_lm"], low_memory=False
    )
    lm = gene_info[gene_info["pr_is_lm"] == 1]
    gene_ids = [int(g) for g in lm["pr_gene_id"].tolist()]
    if not gene_ids:
        raise ValueError("gene_info 中没有 pr_is_lm == 1 的基因: {}".format(gene_info_path))
    return gene_ids


def _read_gene_ids(path: str) -> List[int]:
    """读取 row_gene_ids.csv / drug_median_lm_gene_ids.csv 中的 gene_id 列。"""
    df = pd.read_csv(path)
    if "gene_id" not in df.columns:
        raise ValueError("{} 缺少 gene_id 列".format(path))
    return [int(g) for g in df["gene_id"].tolist()]


def _read_sig_ids(path: str) -> List[str]:
    """读取 col_sig_ids.csv 中的 sig_id 列。"""
    df = pd.read_csv(path)
    if "sig_id" not in df.columns:
        raise ValueError("{} 缺少 sig_id 列".format(path))
    return [str(s) for s in df["sig_id"].tolist()]


def _median_columns(
    matrix: np.ndarray,
    lm_rows: Sequence[int],
    col_indices: Sequence[int],
    chunk_size: int,
) -> np.ndarray:
    """对指定列、landmark 行计算逐行中位数。

    分块读取，避免一次性把某个药物的全部签名 × 12328 基因读进内存。
    """
    blocks = []
    for start in range(0, len(col_indices), chunk_size):
        chunk = list(col_indices[start:start + chunk_size])
        block = np.asarray(matrix[:, chunk])[list(lm_rows), :]
        blocks.append(block)
    values = np.concatenate(blocks, axis=1)
    return np.median(values, axis=1).astype(np.float32)


def build_drug_median(
    data_dir: str,
    sig_info_path: Optional[str] = None,
    gene_info_path: Optional[str] = None,
    matrix_path: Optional[str] = None,
    row_names_path: Optional[str] = None,
    col_names_path: Optional[str] = None,
    out_dir: Optional[str] = None,
    chunk_size: int = 1000,
) -> Dict[str, object]:
    """
    从 cmap_data 构建药物中位数矩阵。

    Args:
        data_dir: cmap 数据目录（通常为 CMAP_DATA_DIR）
        *_path: 各输入文件的显式覆盖路径（测试用）
        out_dir: 输出目录，默认与 data_dir 相同
        chunk_size: 每次读取的签名列数

    Returns:
        dict: matrix_path / names_path / gene_ids_path / shape / n_drug
    """
    (
        default_sig,
        default_gene,
        default_matrix,
        default_rows,
        default_cols,
    ) = _default_paths(data_dir)
    sig_info_path = sig_info_path or default_sig
    gene_info_path = gene_info_path or default_gene
    matrix_path = matrix_path or default_matrix
    row_names_path = row_names_path or default_rows
    col_names_path = col_names_path or default_cols
    out_dir = out_dir or data_dir
    os.makedirs(out_dir, exist_ok=True)

    lm_gene_ids = load_landmark_gene_ids(gene_info_path)
    row_gene_ids = _read_gene_ids(row_names_path)
    sig_ids = _read_sig_ids(col_names_path)

    row_to_idx = {gid: i for i, gid in enumerate(row_gene_ids)}
    missing = [gid for gid in lm_gene_ids if gid not in row_to_idx]
    if missing:
        raise ValueError(
            "{} 个 landmark 基因不在矩阵行名中（例如 {}）".format(len(missing), missing[:5])
        )
    lm_rows = [row_to_idx[gid] for gid in lm_gene_ids]

    col_to_idx = {sid: i for i, sid in enumerate(sig_ids)}
    matrix = np.memmap(
        matrix_path, dtype="float32", mode="r", shape=(len(row_gene_ids), len(sig_ids))
    )

    print("[build_drug_median] 读取 sig_info ...")
    sig_info = pd.read_csv(
        sig_info_path,
        sep="\t",
        compression="gzip",
        usecols=["sig_id", "pert_iname", "pert_type"],
        low_memory=False,
    )
    trt_cp = sig_info[
        (sig_info["pert_type"] == "trt_cp") & (sig_info["pert_iname"].notna())
    ]
    drug_to_sigs = {}
    for name, group in trt_cp.groupby("pert_iname", sort=True):
        drug_to_sigs[str(name)] = [str(s) for s in group["sig_id"].tolist()]

    drug_names = sorted(drug_to_sigs.keys())
    print(
        "[build_drug_median] trt_cp 签名 {} 个，药物 {} 种，landmark 基因 {} 个".format(
            len(trt_cp), len(drug_names), len(lm_gene_ids)
        )
    )

    valid_names = []
    medians = []
    skipped = []
    for i, name in enumerate(drug_names, start=1):
        indices = [col_to_idx[s] for s in drug_to_sigs[name] if s in col_to_idx]
        if not indices:
            skipped.append(name)
            continue
        medians.append(_median_columns(matrix, lm_rows, indices, chunk_size))
        valid_names.append(name)
        if i % 200 == 0 or i == len(drug_names):
            print("[build_drug_median] 进度: {}/{}".format(i, len(drug_names)))

    if not medians:
        raise ValueError("没有可用的 trt_cp 签名，未生成药物矩阵")
    drug_mat = np.stack(medians, axis=1).astype(np.float32, copy=False)
    del matrix  # 释放 memmap 句柄（Windows 下否则文件被锁）

    matrix_out = os.path.join(out_dir, MATRIX_FILENAME)
    names_out = os.path.join(out_dir, NAMES_FILENAME)
    gene_ids_out = os.path.join(out_dir, GENE_IDS_FILENAME)
    np.save(matrix_out, drug_mat)
    pd.DataFrame({"pert_iname": valid_names}).to_csv(names_out, index=False)
    pd.DataFrame({"gene_id": lm_gene_ids}).to_csv(gene_ids_out, index=False)

    if skipped:
        print(
            "[build_drug_median] 警告：{} 个药物没有对应的矩阵列，已跳过（例如 {}）".format(
                len(skipped), skipped[:5]
            )
        )
    print(
        "[build_drug_median] 完成: {} × {} → {}".format(
            drug_mat.shape[0], drug_mat.shape[1], matrix_out
        )
    )
    return {
        "matrix_path": matrix_out,
        "names_path": names_out,
        "gene_ids_path": gene_ids_out,
        "shape": tuple(int(x) for x in drug_mat.shape),
        "n_drug": int(drug_mat.shape[1]),
        "n_landmark": int(drug_mat.shape[0]),
        "skipped_drugs": skipped,
    }


def _find_lmna_files(lmna_dir: str) -> Tuple[str, str]:
    """在 LMNA 缓存目录中定位矩阵与药名文件（优先 v2）。"""
    matrix_candidates = [
        "_drug_median_matrix.v2.npy",
        "_drug_median_matrix.npy",
    ]
    names_candidates = [
        "_drug_names.v2.csv",
        "_drug_names.csv",
    ]
    matrix_path = next(
        (os.path.join(lmna_dir, n) for n in matrix_candidates
         if os.path.exists(os.path.join(lmna_dir, n))),
        None,
    )
    names_path = next(
        (os.path.join(lmna_dir, n) for n in names_candidates
         if os.path.exists(os.path.join(lmna_dir, n))),
        None,
    )
    if matrix_path is None or names_path is None:
        raise FileNotFoundError(
            "在 {} 中找不到 _drug_median_matrix[.v2].npy / _drug_names[.v2].csv".format(
                lmna_dir
            )
        )
    return matrix_path, names_path


def _read_drug_names(path: str) -> List[str]:
    """读取 LMNA 药名 CSV（列名 drug_name，兼容 pert_iname / 首列）。"""
    df = pd.read_csv(path)
    for col in ("drug_name", "pert_iname"):
        if col in df.columns:
            return [str(x) for x in df[col].tolist()]
    if df.shape[1] == 0:
        raise ValueError("药名文件没有列: {}".format(path))
    return [str(x) for x in df.iloc[:, 0].tolist()]


def import_from_lmna(
    lmna_dir: str,
    data_dir: str,
    gene_info_path: Optional[str] = None,
    out_dir: Optional[str] = None,
) -> Dict[str, object]:
    """复用 LMNA 已生成的药物中位数矩阵，写入本仓库 DATA_DIR。"""
    gene_info_path = gene_info_path or os.path.join(
        data_dir, "GSE92742_Broad_LINCS_gene_info.txt.gz"
    )
    out_dir = out_dir or data_dir
    os.makedirs(out_dir, exist_ok=True)

    matrix_src, names_src = _find_lmna_files(lmna_dir)
    lm_gene_ids = load_landmark_gene_ids(gene_info_path)
    names = _read_drug_names(names_src)

    # mmap 只读，随后一次性写入新 .npy（77MB 量级，离线脚本可接受）
    src = np.load(matrix_src, mmap_mode="r")
    if src.ndim != 2:
        raise ValueError("LMNA 药物矩阵不是二维: {}".format(src.shape))
    if src.shape[0] != len(lm_gene_ids):
        raise ValueError(
            "LMNA 矩阵行数 {} 与本地 landmark 基因数 {} 不一致；"
            "请确认两边使用同一份 gene_info".format(src.shape[0], len(lm_gene_ids))
        )
    if src.shape[1] != len(names):
        raise ValueError(
            "LMNA 矩阵列数 {} 与药名数 {} 不一致".format(src.shape[1], len(names))
        )

    drug_mat = np.asarray(src, dtype=np.float32)
    del src

    matrix_out = os.path.join(out_dir, MATRIX_FILENAME)
    names_out = os.path.join(out_dir, NAMES_FILENAME)
    gene_ids_out = os.path.join(out_dir, GENE_IDS_FILENAME)
    np.save(matrix_out, drug_mat)
    pd.DataFrame({"pert_iname": names}).to_csv(names_out, index=False)
    pd.DataFrame({"gene_id": lm_gene_ids}).to_csv(gene_ids_out, index=False)

    print(
        "[build_drug_median] 已复用 LMNA 矩阵: {} × {} → {}".format(
            drug_mat.shape[0], drug_mat.shape[1], matrix_out
        )
    )
    return {
        "matrix_path": matrix_out,
        "names_path": names_out,
        "gene_ids_path": gene_ids_out,
        "shape": tuple(int(x) for x in drug_mat.shape),
        "n_drug": int(drug_mat.shape[1]),
        "n_landmark": int(drug_mat.shape[0]),
        "source_matrix": matrix_src,
        "source_names": names_src,
    }


def main():
    parser = argparse.ArgumentParser(description="构建药物 × landmark 中位数矩阵")
    parser.add_argument(
        "--data-dir", default=None, help="cmap 数据目录（默认 CMAP_DATA_DIR）"
    )
    parser.add_argument("--out-dir", default=None, help="输出目录（默认同 data-dir）")
    parser.add_argument(
        "--from-lmna",
        default=None,
        metavar="DIR",
        help="复用 LMNA 缓存目录中的 _drug_median_matrix[.v2].npy + _drug_names[.v2].csv",
    )
    parser.add_argument("--sig-info", default=None, help="sig_info 路径覆盖")
    parser.add_argument("--gene-info", default=None, help="gene_info 路径覆盖")
    parser.add_argument("--matrix", default=None, help="fast_matrix.npy 路径覆盖")
    parser.add_argument("--row-names", default=None, help="row_gene_ids.csv 路径覆盖")
    parser.add_argument("--col-names", default=None, help="col_sig_ids.csv 路径覆盖")
    parser.add_argument("--chunk-size", type=int, default=1000, help="每次读取的签名列数")
    args = parser.parse_args()
    if args.data_dir is None:
        args.data_dir = _default_data_dir()

    if args.from_lmna:
        import_from_lmna(
            args.from_lmna, args.data_dir, gene_info_path=args.gene_info, out_dir=args.out_dir
        )
    else:
        build_drug_median(
            args.data_dir,
            sig_info_path=args.sig_info,
            gene_info_path=args.gene_info,
            matrix_path=args.matrix,
            row_names_path=args.row_names,
            col_names_path=args.col_names,
            out_dir=args.out_dir,
            chunk_size=args.chunk_size,
        )


if __name__ == "__main__":
    main()
