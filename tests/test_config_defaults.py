#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验收项：不设环境变量时，所有路径/维度与改动前完全一致

在子进程中清空 CMAP_* 环境变量后 import app.config，
逐一比对默认值（改动前的硬编码值）。
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHECK_SCRIPT = r"""
import os, sys
for k in list(os.environ):
    if k.startswith("CMAP_"):
        del os.environ[k]
sys.path.insert(0, sys.argv[1])
from app import config
root = config.PROJECT_ROOT
assert config.DATA_DIR == os.path.join(root, "cmap_data"), config.DATA_DIR
assert config.MATRIX_PATH == os.path.join(root, "cmap_data", "fast_matrix.npy")
assert config.COL_NAMES_PATH == os.path.join(root, "cmap_data", "col_sig_ids.csv")
assert config.ROW_NAMES_PATH == os.path.join(root, "cmap_data", "row_gene_ids.csv")
assert config.SIG_INFO_PATH == os.path.join(
    root, "cmap_data", "GSE92742_Broad_LINCS_sig_info.txt.gz")
assert config.GENE_INFO_PATH == os.path.join(
    root, "cmap_data", "GSE92742_Broad_LINCS_gene_info.txt.gz")
assert config.PERT_INFO_PATH == os.path.join(
    root, "cmap_data", "GSE92742_Broad_LINCS_pert_info.txt.gz")
assert config.TOUCHSTONE_DIR == os.path.join(root, "touchstone_data")
assert config.N_GENES == 12328, config.N_GENES
assert config.N_SIGS == 473647, config.N_SIGS
assert config.TEMP_DIR == os.path.join(root, "temp")
print("defaults OK")
"""


def test_defaults_unchanged_without_env_vars():
    """不设置 CMAP_* 环境变量时，config 默认值与改动前一致"""
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT, PROJECT_ROOT],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "defaults OK" in result.stdout
