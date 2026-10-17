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

# ============ 药物中位数矩阵（C3 方案 B：查询内随机签名 null） ============
# 由 scripts/build_drug_median.py 生成；978 × n_drug，float32。
# 矩阵只放在 CMAP_DATA_DIR 下，不进 git。
DRUG_MEDIAN_MATRIX_PATH = os.getenv(
    "CMAP_DRUG_MEDIAN_MATRIX", os.path.join(DATA_DIR, "drug_median_lm.npy")
)
DRUG_MEDIAN_NAMES_PATH = os.getenv(
    "CMAP_DRUG_MEDIAN_NAMES", os.path.join(DATA_DIR, "drug_median_names.csv")
)
DRUG_MEDIAN_GENE_IDS_PATH = os.getenv(
    "CMAP_DRUG_MEDIAN_GENE_IDS", os.path.join(DATA_DIR, "drug_median_lm_gene_ids.csv")
)

# 随机签名 null 参数（🧑‍⚖️ 可用环境变量调整）
NULL_CALIBRATION_N = int(os.getenv("CMAP_NULL_N", "10000"))
NULL_CALIBRATION_SEED = int(os.getenv("CMAP_NULL_SEED", "0"))
NULL_CALIBRATION_BATCH = int(os.getenv("CMAP_NULL_BATCH", "500"))
NULL_CALIBRATION_MIN_GENES = int(os.getenv("CMAP_NULL_MIN_GENES", "10"))

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

# CSV 导入 topN 上限（🧑‍⚖️ D7：默认 150，可用 CMAP_CSV_TOP_N_MAX 调整）
CSV_TOP_N_MAX = int(os.getenv("CMAP_CSV_TOP_N_MAX", "150"))
