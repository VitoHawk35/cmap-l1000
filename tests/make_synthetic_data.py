#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
合成测试数据集生成器

生成一个能让全部接口跑通的小数据集（默认 N_GENES=200, N_SIGS=3000），
文件格式与真实 cmap_data 完全一致（裸 float32 memmap + gzip TSV 元数据）。

埋一个"已知逆转药" reversib：其所有签名在 up 基因上 z=-3、down 基因上 z=+3，
其余签名为 N(0,1) 噪声；Touchstone 药物带 ±0.5 的确定性倾斜，
保证 NCS 归一化与 Tau 参考分布同时有正有负。

用法：
    python tests/make_synthetic_data.py --dir /path/to/cmap_data
    # 然后设置环境变量：
    #   CMAP_DATA_DIR=/path/to/cmap_data CMAP_N_GENES=200 CMAP_N_SIGS=3000
"""

import argparse
import os
from typing import Dict, List

import numpy as np
import pandas as pd

# 数据集固定参数
N_GENES = 200
N_SIGS = 3000
N_DRUGS = 60          # 60 药物 × 5 细胞系 × 10 剂量 = 3000 签名
N_CELLS = 5
N_DOSES = 10
N_TOUCHSTONE = 40     # 其中 40 个药物 is_touchstone=1

REVERSAL_DRUG = "reversib"      # 埋入的已知逆转药（非 touchstone）
N_UP = 20             # 查询上调基因数（对应 row_gene_ids 前 20 个）
N_DOWN = 15           # 查询下调基因数（对应之后 15 个）

CELLS = ["A375", "MCF7", "PC3", "HT29", "A549"]


def make_synthetic_data(data_dir: str, n_genes: int = N_GENES, n_sigs: int = N_SIGS,
                        seed: int = 42) -> Dict[str, object]:
    """
    在给定目录生成合成数据集。

    Args:
        data_dir: 输出目录（不存在则创建）
        n_genes: 基因数（矩阵行数），默认 200
        n_sigs: 签名数（矩阵列数），默认 3000；必须等于 60×5×10

    Returns:
        dict: 数据集信息（基因 ID、上下调基因、逆转药名等），供测试断言使用
    """
    if n_sigs != N_DRUGS * N_CELLS * N_DOSES:
        raise ValueError(
            f"n_sigs={n_sigs} 必须等于 {N_DRUGS}×{N_CELLS}×{N_DOSES}="
            f"{N_DRUGS * N_CELLS * N_DOSES}（药物×细胞系×剂量）"
        )

    os.makedirs(data_dir, exist_ok=True)
    rng = np.random.RandomState(seed)

    # ---------- 基因 ----------
    gene_ids = [10001 + i for i in range(n_genes)]  # 伪造 Entrez ID
    up_gene_ids = gene_ids[:N_UP]
    down_gene_ids = gene_ids[N_UP:N_UP + N_DOWN]
    up_idx = np.arange(N_UP)
    down_idx = np.arange(N_UP, N_UP + N_DOWN)

    # ---------- 扰动（药物） ----------
    # 药物 0 = reversib（逆转药）；共 40 个 touchstone（含 reversib）。
    # reversib 必须是 touchstone 且是其中最负的：Tau 公式中 neg_ref 的最小值
    # 恰好取得 tau=-100（-mean(x<=neg_ref)*100，min≤所有元素→-100），若 reversib
    # 不在 touchstone 参考内，会与最负的 touchstone 药并列 -100，排名取决于
    # 不稳定的排序 tie-break；作为参考集内最负成员则唯一取得 -100。
    pert_ids = [f"BRD-TEST-{i:04d}" for i in range(N_DRUGS)]
    pert_inames = [REVERSAL_DRUG] + [f"drug-{i:03d}" for i in range(1, N_DRUGS)]
    is_touchstone = [1 if (i == 0 or i > N_DRUGS - N_TOUCHSTONE) else 0
                     for i in range(N_DRUGS)]

    # ---------- 元数据（签名按 药物×细胞系×剂量 顺序排布，列索引即顺序号） ----------
    sig_rows = []  # type: List[Dict[str, str]]
    sig_order = []  # type: List[tuple]  # (col_idx, drug_i, cell_i, dose_i)
    col = 0
    for d in range(N_DRUGS):
        for c in range(N_CELLS):
            for dose in range(N_DOSES):
                sig_id = f"SIG{col:06d}"
                sig_rows.append({
                    "sig_id": sig_id,
                    "pert_id": pert_ids[d],
                    "pert_iname": pert_inames[d],
                    "cell_id": CELLS[c],
                    "pert_idose": f"{(dose + 1)} uM",
                    "pert_time": "24 h",
                    "pert_type": "trt_cp",
                })
                sig_order.append((col, d, c, dose))
                col += 1

    # ---------- 表达矩阵（裸 float32 memmap，无 .npy 文件头！） ----------
    # 结构仿真实 LINCS：同一 (药物, 细胞系) 的剂量重复高度相关
    # （共享 base 向量 + 0.1σ 噪声），否则纯随机排序的 WTCS 极值噪声
    # 会让某个 touchstone 药在药物级聚合后盖过埋入的逆转药。
    matrix_path = os.path.join(data_dir, "fast_matrix.npy")
    mat = np.memmap(matrix_path, dtype="float32", mode="w+", shape=(n_genes, n_sigs))

    # 每个 (药物, 细胞系) 一个 base 向量（含该药物的确定性倾斜）
    base_vectors = {}  # type: Dict[tuple, np.ndarray]
    for d in range(N_DRUGS):
        for c in range(N_CELLS):
            base = rng.standard_normal(n_genes)
            if d == 0:
                # 逆转药：up 基因压低、down 基因抬高
                base[up_idx] = -3.0
                base[down_idx] = 3.0
            elif is_touchstone[d]:
                # Touchstone 参考：一半偏正（与疾病相似）、一半偏负（弱逆转），
                # 保证 Tau 计算的正/负参考分布均非空
                if d % 2 == 0:
                    base[up_idx] += 0.5
                    base[down_idx] -= 0.5
                else:
                    base[up_idx] -= 0.5
                    base[down_idx] += 0.5
            base_vectors[(d, c)] = base.astype(np.float32)

    for col_idx, d, c, _dose in sig_order:
        mat[:, col_idx] = base_vectors[(d, c)] + (
            0.1 * rng.standard_normal(n_genes)).astype(np.float32)
    mat.flush()
    del mat  # 释放 memmap 句柄（Windows 下必须，否则文件被锁）

    # ---------- 列/行名文件 ----------
    pd.DataFrame({"sig_id": [r["sig_id"] for r in sig_rows]}).to_csv(
        os.path.join(data_dir, "col_sig_ids.csv"), index=False)
    pd.DataFrame({"gene_id": gene_ids}).to_csv(
        os.path.join(data_dir, "row_gene_ids.csv"), index=False)

    # ---------- 元数据 gzip TSV ----------
    pd.DataFrame(sig_rows).to_csv(
        os.path.join(data_dir, "GSE92742_Broad_LINCS_sig_info.txt.gz"),
        sep="\t", compression="gzip", index=False)

    pert_info = pd.DataFrame({
        "pert_id": pert_ids,
        "pert_iname": pert_inames,
        "pert_type": ["trt_cp"] * N_DRUGS,
        "is_touchstone": is_touchstone,
    })
    pert_info.to_csv(
        os.path.join(data_dir, "GSE92742_Broad_LINCS_pert_info.txt.gz"),
        sep="\t", compression="gzip", index=False)

    gene_info = pd.DataFrame({
        "pr_gene_id": gene_ids,
        "pr_gene_symbol": [f"GENE{g}" for g in gene_ids],
        "pr_is_lm": [1] * n_genes,
    })
    gene_info.to_csv(
        os.path.join(data_dir, "GSE92742_Broad_LINCS_gene_info.txt.gz"),
        sep="\t", compression="gzip", index=False)

    return {
        "data_dir": data_dir,
        "n_genes": n_genes,
        "n_sigs": n_sigs,
        "gene_ids": gene_ids,
        "up_gene_ids": up_gene_ids,
        "down_gene_ids": down_gene_ids,
        "reversal_drug": REVERSAL_DRUG,
        "n_touchstone": N_TOUCHSTONE,
    }


def main():
    parser = argparse.ArgumentParser(description="生成 cmap 合成测试数据集")
    parser.add_argument("--dir", required=True, help="输出目录")
    parser.add_argument("--genes", type=int, default=N_GENES, help="基因数（默认 200）")
    parser.add_argument("--sigs", type=int, default=N_SIGS, help="签名数（默认 3000）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    info = make_synthetic_data(args.dir, n_genes=args.genes, n_sigs=args.sigs,
                               seed=args.seed)
    print(f"合成数据集已生成: {info['data_dir']}")
    print(f"  矩阵: {info['n_genes']} genes × {info['n_sigs']} sigs")
    print(f"  逆转药: {info['reversal_drug']} (up={info['up_gene_ids'][:3]}..., "
          f"down={info['down_gene_ids'][:3]}...)")
    print("请设置环境变量：")
    print(f"  CMAP_DATA_DIR={info['data_dir']}")
    print(f"  CMAP_N_GENES={info['n_genes']}")
    print(f"  CMAP_N_SIGS={info['n_sigs']}")


if __name__ == "__main__":
    main()
