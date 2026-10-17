#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全局配置管理
"""

import os
from typing import List

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录（可用环境变量覆盖，便于测试时使用小型合成数据集）
DATA_DIR = os.getenv("CMAP_DATA_DIR", os.path.join(PROJECT_ROOT, "cmap_data"))

# ============ 文件路径 ============
# 核心数据文件
MATRIX_PATH = os.path.join(DATA_DIR, "fast_matrix.npy")
COL_NAMES_PATH = os.path.join(DATA_DIR, "col_sig_ids.csv")
ROW_NAMES_PATH = os.path.join(DATA_DIR, "row_gene_ids.csv")

# 原始元数据文件
SIG_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_sig_info.txt.gz")
GENE_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_gene_info.txt.gz")
PERT_INFO_PATH = os.path.join(DATA_DIR, "GSE92742_Broad_LINCS_pert_info.txt.gz")

# Touchstone 核心参考数据库（用于 NCS 归一化和 Tau 计算）
TOUCHSTONE_DIR = os.getenv("CMAP_TOUCHSTONE_DIR", os.path.join(PROJECT_ROOT, "touchstone_data"))
TOUCHSTONE_GCTX_PATH = os.path.join(TOUCHSTONE_DIR, "touchstone_score.gctx")
TOUCHSTONE_SIGINFO_PATH = os.path.join(TOUCHSTONE_DIR, "touchstone_siginfo.txt")

# ============ 矩阵维度 ============
# 可用环境变量覆盖，测试时使用小矩阵
N_GENES = int(os.getenv("CMAP_N_GENES", "12328"))
N_SIGS = int(os.getenv("CMAP_N_SIGS", "473647"))

# ============ 临时目录（任务/导出 token 持久化） ============
TEMP_DIR = os.getenv("CMAP_TEMP_DIR", os.path.join(PROJECT_ROOT, "temp"))

# ============ API 配置 ============
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ============ 搜索配置 ============
DEFAULT_TOP_K = 50
CHUNK_SIZE_FOR_BATCH = 10000  # 批量处理时的分块大小
