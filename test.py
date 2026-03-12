#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试脚本：读取测试数据.xlsx，映射基因，用 Cosine 和 WTCS 算法跑一遍
"""

import pandas as pd
import numpy as np
import gzip
from app.core.metadata_index import MetadataIndex
from app.core.matrix_store import MatrixStore
from app.scoring.cosine_scorer import CosineScorer
from app.scoring.wtcs_scorer import WTCSScorer
from app.config import N_GENES, ROW_NAMES_PATH, GENE_INFO_PATH


def load_gene_mapping():
    """加载 gene symbol -> Entrez ID 映射"""
    df = pd.read_csv(GENE_INFO_PATH, sep='\t', compression='gzip')
    symbol_to_entrez = {}
    for _, row in df.iterrows():
        symbol = str(row['pr_gene_symbol']).upper().strip()
        entrez_id = int(row['pr_gene_id'])
        symbol_to_entrez[symbol] = entrez_id
    return symbol_to_entrez


def load_row_mapping():
    """加载 Entrez ID -> 矩阵行索引映射"""
    row_df = pd.read_csv(ROW_NAMES_PATH)
    gene_ids = row_df['gene_id'].astype(str).tolist()
    return {gene_id: idx for idx, gene_id in enumerate(gene_ids)}


def main():
    print("=" * 70)
    print("CMAP L1000 测试脚本")
    print("=" * 70)

    # 1. 读取测试数据
    print("\n[1/5] 读取测试数据...")
    df = pd.read_excel('cmap_data/测试数据.xlsx')
    print(f"    文件形状: {df.shape}")
    print(f"    列名: {df.columns.tolist()}")

    # 获取上下调基因（第1列是上调，第3列是下调）
    up_genes_raw = df.iloc[:, 0].dropna().astype(str).str.upper().str.strip().tolist()
    down_genes_raw = df.iloc[:, 2].dropna().astype(str).str.upper().str.strip().tolist()

    print(f"\n    原始上调基因数: {len(up_genes_raw)}")
    print(f"    原始下调基因数: {len(down_genes_raw)}")

    # 2. 基因映射
    print("\n[2/5] 映射基因到 Entrez ID...")
    symbol_to_entrez = load_gene_mapping()
    print(f"    基因映射表大小: {len(symbol_to_entrez)}")

    up_genes = []
    down_genes = []
    missing_up = []
    missing_down = []

    for symbol in up_genes_raw:
        if symbol in symbol_to_entrez:
            up_genes.append(symbol_to_entrez[symbol])
        else:
            missing_up.append(symbol)

    for symbol in down_genes_raw:
        if symbol in symbol_to_entrez:
            down_genes.append(symbol_to_entrez[symbol])
        else:
            missing_down.append(symbol)

    print(f"\n    上调基因映射成功: {len(up_genes)}/{len(up_genes_raw)}")
    print(f"    下调基因映射成功: {len(down_genes)}/{len(down_genes_raw)}")

    if missing_up:
        print(f"\n    [警告] 上调基因未匹配 ({len(missing_up)}个): {missing_up}")
    if missing_down:
        print(f"    [警告] 下调基因未匹配 ({len(missing_down)}个): {missing_down}")

    if not up_genes or not down_genes:
        print("\n❌ 错误: 有效基因数量不足，无法继续测试")
        return

    # 3. 转换为矩阵索引
    print("\n[3/5] 转换为矩阵行索引...")
    gene_to_idx = load_row_mapping()

    up_indices = [gene_to_idx[str(g)] for g in up_genes if str(g) in gene_to_idx]
    down_indices = [gene_to_idx[str(g)] for g in down_genes if str(g) in gene_to_idx]

    print(f"    上调基因有效索引: {len(up_indices)}")
    print(f"    下调基因有效索引: {len(down_indices)}")

    # 4. Cosine 算法测试
    print("\n[4/5] 运行 Cosine 算法...")
    matrix_store = MatrixStore()
    metadata_index = MetadataIndex()
    cosine_scorer = CosineScorer()

    query_vector = np.zeros(N_GENES, dtype=np.float32)
    for idx in up_indices:
        query_vector[idx] = 1.0
    for idx in down_indices:
        query_vector[idx] = -1.0

    batch_iterator = matrix_store.get_batch_iterator(batch_size=10000)
    top_indices, top_scores, bottom_indices, bottom_scores = cosine_scorer.top_k_both(
        query_vector, batch_iterator, k=50
    )

    print(f"\n    Cosine Top 50 (最能逆转):")
    top_metadata = metadata_index.get_by_indices(top_indices)
    for i, (meta, score) in enumerate(zip(top_metadata, top_scores), 1):
        print(f"      {i}. {meta.pert_iname} ({meta.cell_id}) - 分数: {score:.6f}")

    print(f"\n    Cosine Bottom 50 (最相似):")
    bottom_metadata = metadata_index.get_by_indices(bottom_indices)
    for i, (meta, score) in enumerate(zip(bottom_metadata, bottom_scores), 1):
        print(f"      {i}. {meta.pert_iname} ({meta.cell_id}) - 分数: {score:.6f}")

    # 5. WTCS 算法测试
    print("\n[5/5] 运行 WTCS 算法...")
    wtcs_scorer = WTCSScorer(up_indices, down_indices)

    batch_iterator = matrix_store.get_batch_iterator(batch_size=5000)
    # WTCS 需要 query 参数（虽然不使用），传一个空向量
    dummy_query = np.zeros(N_GENES, dtype=np.float32)
    wtcs_top_idx, wtcs_top_scores, wtcs_bottom_idx, wtcs_bottom_scores = wtcs_scorer.top_k_both(
        dummy_query, batch_iterator, k=50
    )

    print(f"\n    WTCS Top 50 (最能逆转):")
    top_metadata = metadata_index.get_by_indices(wtcs_top_idx)
    for i, (meta, score) in enumerate(zip(top_metadata, wtcs_top_scores), 1):
        print(f"      {i}. {meta.pert_iname} ({meta.cell_id}) - WTCS: {score:.6f}")

    print(f"\n    WTCS Bottom 50 (最相似):")
    bottom_metadata = metadata_index.get_by_indices(wtcs_bottom_idx)
    for i, (meta, score) in enumerate(zip(bottom_metadata, wtcs_bottom_scores), 1):
        print(f"      {i}. {meta.pert_iname} ({meta.cell_id}) - WTCS: {score:.6f}")

    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
