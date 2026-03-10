#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全局配置管理
"""

import os
from typing import List

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录
DATA_DIR = os.path.join(PROJECT_ROOT, "cmap_data")

# ============ 文件路径 ============
# 核心数据文件
MATRIX_PATH = os.path.join(DATA_DIR, "fast_matrix.npy")
COL_NAMES_PATH = os.path.join(DATA_DIR, "col_sig_ids.csv")
ROW_NAMES_PATH = os.path.join(DATA_DIR, "row_gene_ids.csv")

# 原始元数据文件
SIG_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_sig_info.txt.gz")
GENE_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_gene_info.txt.gz")

# ============ 矩阵维度 ============
N_GENES = 12328
N_SIGS = 473647

# ============ API 配置 ============
API_HOST = "0.0.0.0"
API_PORT = 8000

# ============ 搜索配置 ============
DEFAULT_TOP_K = 50
CHUNK_SIZE_FOR_BATCH = 10000  # 批量处理时的分块大小
