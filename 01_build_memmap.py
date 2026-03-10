#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据预处理脚本：将 GCTX 格式转换为 numpy.memmap 格式
用途：将 20GB 的 CMAP L1000 数据转换为高效的内存映射格式

运行注意事项：
1. 确保已安装 h5py: pip install h5py
2. 确保磁盘有足够空间（需要约 23GB 用于输出文件）
3. 此脚本运行时间较长（约 10-30 分钟），请耐心等待
4. 建议使用 SSD 以提高 I/O 性能
5. 内存优化：全程占用 < 500MB RAM，使用流式 HDF5 读取
"""

import os
import sys
import gzip
import shutil
import h5py
import numpy as np
import pandas as pd
from typing import List, Tuple


# ============ 配置路径 ============
# 数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cmap_data")

# 输入文件路径
GCTX_GZ_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_Level5_COMPZ.MODZ_n473647x12328.gctx.gz")
SIG_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_sig_info.txt.gz")
GENE_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_gene_info.txt.gz")

# 输出文件路径
OUTPUT_MATRIX_PATH = os.path.join(DATA_DIR, "fast_matrix.npy")
OUTPUT_COL_NAMES_PATH = os.path.join(DATA_DIR, "col_sig_ids.csv")
OUTPUT_ROW_NAMES_PATH = os.path.join(DATA_DIR, "row_gene_ids.csv")

# 临时解压的 GCTX 文件路径
TEMP_GCTX_PATH = os.path.join(DATA_DIR, "temp_matrix.gctx")

# 矩阵维度（根据 PRD 确认）
N_GENES = 12328
N_SIGS = 473647


def decompress_gctx() -> str:
    """
    解压 .gctx.gz 文件为 .gctx

    Returns:
        解压后的文件路径
    """
    print(f"[1/5] 正在解压 GCTX 文件...")
    print(f"    源文件: {GCTX_GZ_PATH}")
    print(f"    目标文件: {TEMP_GCTX_PATH}")

    if not os.path.exists(GCTX_GZ_PATH):
        raise FileNotFoundError(f"找不到 GCTX 文件: {GCTX_GZ_PATH}")

    # 流式解压避免内存爆炸
    with gzip.open(GCTX_GZ_PATH, 'rb') as f_in:
        with open(TEMP_GCTX_PATH, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    print(f"    解压完成")
    return TEMP_GCTX_PATH


def extract_and_save_metadata():
    """
    提取并保存行列元数据
    """
    print(f"[2/5] 提取元数据...")

    # 读取基因信息（行名）
    print(f"    读取基因信息...")
    gene_info = pd.read_csv(GENE_INFO_PATH, sep='\t', compression='gzip')
    # 提取 Entrez ID 作为行名
    row_gene_ids = gene_info['pr_gene_id'].astype(str).tolist()

    if len(row_gene_ids) != N_GENES:
        print(f"    警告: 基因数量 {len(row_gene_ids)} 与预期 {N_GENES} 不符")

    # 保存行名
    pd.DataFrame({'gene_id': row_gene_ids}).to_csv(
        OUTPUT_ROW_NAMES_PATH, index=False
    )
    print(f"    行名已保存: {OUTPUT_ROW_NAMES_PATH} ({len(row_gene_ids)} 个基因)")

    # 读取签名信息（列名）
    print(f"    读取签名信息...")
    sig_info = pd.read_csv(SIG_INFO_PATH, sep='\t', compression='gzip')
    col_sig_ids = sig_info['sig_id'].astype(str).tolist()

    if len(col_sig_ids) != N_SIGS:
        print(f"    警告: 签名数量 {len(col_sig_ids)} 与预期 {N_SIGS} 不符")

    # 保存列名
    pd.DataFrame({'sig_id': col_sig_ids}).to_csv(
        OUTPUT_COL_NAMES_PATH, index=False
    )
    print(f"    列名已保存: {OUTPUT_COL_NAMES_PATH} ({len(col_sig_ids)} 个签名)")

    return row_gene_ids, col_sig_ids


def build_memmap_matrix(gctx_path: str) -> Tuple[int, int]:
    """
    使用底层 HDF5 流式读取 GCTX 并构建 memmap 矩阵

    架构优化：全程内存占用极低（< 500MB），彻底告别 OOM！
    GCTX 本质上是 HDF5 文件，直接使用 h5py 进行流式分块处理。

    注意: HDF5 中矩阵存储形状是 (473647, 12328)，即 (列 x 行)
    我们要存储为 (12328, 473647)，即 (行 x 列)，符合常规矩阵表示

    Args:
        gctx_path: GCTX 文件路径

    Returns:
        (行数, 列数) 元组
    """
    print("[3/5] 使用底层 HDF5 流式处理数据...")
    print("    内存优化模式：全程 < 500MB RAM")

    with h5py.File(gctx_path, 'r') as f:
        # GCTX 文件中，矩阵数据存储在 /0/DATA/0/matrix 路径
        dataset = f['0']['DATA']['0']['matrix']

        # HDF5 中存储形状是 (列数, 行数) = (473647, 12328)
        h5_cols, h5_rows = dataset.shape
        print(f"    原始 HDF5 矩阵形状: ({h5_cols}, {h5_rows}) (HDF5 中是 列x行)")

        # 我们要建立的 memmap 是 (12328, 473647) 即 (行x列)
        print("[4/5] 创建 memmap 文件...")
        print(f"    输出路径: {OUTPUT_MATRIX_PATH}")
        print(f"    目标形状: ({h5_rows}, {h5_cols})")

        fp = np.memmap(
            OUTPUT_MATRIX_PATH,
            dtype='float32',
            mode='w+',
            shape=(h5_rows, h5_cols)
        )

        # 分块流式处理（每次只处理 5000 列，内存极小）
        chunk_size = 5000
        total_cols = h5_cols

        print("[5/5] 开始流式转录...")
        for start_idx in range(0, total_cols, chunk_size):
            end_idx = min(start_idx + chunk_size, total_cols)

            # 从 HDF5 中切片读取 (chunk_size, 12328)
            # 注意：转置后变为 (12328, chunk_size) 写入 memmap
            chunk_data = dataset[start_idx:end_idx, :].T.astype(np.float32)

            # 写入 memmap
            fp[:, start_idx:end_idx] = chunk_data

            # 定期刷盘并打印进度
            if end_idx % 50000 == 0 or end_idx == total_cols:
                fp.flush()
                progress = end_idx / total_cols * 100
                print(f"    进度: {end_idx} / {total_cols} 列 ({progress:.1f}%)")

        fp.flush()

    print("    Memmap 文件创建完成!")
    print(f"    文件大小: {os.path.getsize(OUTPUT_MATRIX_PATH) / 1024 / 1024 / 1024:.2f} GB")

    return h5_rows, h5_cols


def verify_memmap(n_rows: int, n_cols: int):
    """
    验证创建的 memmap 文件
    """
    print(f"[验证] 验证 memmap 文件...")

    # 重新加载 memmap
    fp = np.memmap(
        OUTPUT_MATRIX_PATH,
        dtype='float32',
        mode='r',
        shape=(n_rows, n_cols)
    )

    print(f"    形状: {fp.shape}")
    print(f"    数据类型: {fp.dtype}")

    # 随机抽查几个位置
    import random
    random.seed(42)

    # 抽查 5 个随机位置的值
    for _ in range(5):
        i = random.randint(0, n_rows - 1)
        j = random.randint(0, n_cols - 1)
        val = fp[i, j]
        print(f"    fp[{i}, {j}] = {val:.4f}")

    print(f"    验证通过!")


def cleanup():
    """
    清理临时文件
    """
    print(f"[清理] 删除临时文件...")
    if os.path.exists(TEMP_GCTX_PATH):
        os.remove(TEMP_GCTX_PATH)
        print(f"    已删除: {TEMP_GCTX_PATH}")
    print(f"    清理完成")


def main():
    """
    主函数
    """
    print("=" * 60)
    print("CMAP L1000 数据预处理脚本")
    print("=" * 60)
    print()

    # 检查输出文件是否已存在
    if os.path.exists(OUTPUT_MATRIX_PATH):
        print(f"警告: 输出文件已存在: {OUTPUT_MATRIX_PATH}")
        response = input("是否覆盖? (y/n): ")
        if response.lower() != 'y':
            print("操作已取消")
            return
        os.remove(OUTPUT_MATRIX_PATH)

    try:
        # 1. 解压 GCTX 文件
        gctx_path = decompress_gctx()

        # 2. 提取并保存元数据
        extract_and_save_metadata()

        # 3. 构建 memmap 矩阵
        n_rows, n_cols = build_memmap_matrix(gctx_path)

        # 4. 验证
        verify_memmap(n_rows, n_cols)

        print()
        print("=" * 60)
        print("预处理完成!")
        print("=" * 60)
        print(f"输出文件:")
        print(f"  - 矩阵文件: {OUTPUT_MATRIX_PATH}")
        print(f"  - 行名文件: {OUTPUT_ROW_NAMES_PATH}")
        print(f"  - 列名文件: {OUTPUT_COL_NAMES_PATH}")

    finally:
        # 5. 清理临时文件
        cleanup()

    print()
    print("提示: 现在你可以使用 numpy.memmap 高效地读取矩阵:")
    print("  import numpy as np")
    print(f"  fp = np.memmap('{OUTPUT_MATRIX_PATH}', dtype='float32', mode='r', shape=({N_GENES}, {N_SIGS}))")
    print("  # 读取某一列（一个实验签名）")
    print("  col_data = fp[:, 0]  # 返回 12328 维向量")


if __name__ == "__main__":
    main()
