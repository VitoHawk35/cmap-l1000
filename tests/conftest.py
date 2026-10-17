#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pytest 配置：session 级合成数据 + TestClient

关键：必须在 import app 之前设置 CMAP_* 环境变量，
因为 app.config 在 import 时读取环境变量确定数据路径与矩阵维度。
"""

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
for _p in (PROJECT_ROOT, TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from make_synthetic_data import make_synthetic_data  # noqa: E402


@pytest.fixture(scope="session")
def synthetic_data(tmp_path_factory):
    """
    生成合成数据集到临时目录，并在 import app 之前设置环境变量。

    Returns:
        dict: make_synthetic_data 返回的数据集信息（基因 ID、逆转药名等）
    """
    data_dir = tmp_path_factory.mktemp("cmap_data")
    temp_dir = tmp_path_factory.mktemp("cmap_temp")

    info = make_synthetic_data(str(data_dir))

    os.environ["CMAP_DATA_DIR"] = str(data_dir)
    os.environ["CMAP_N_GENES"] = str(info["n_genes"])
    os.environ["CMAP_N_SIGS"] = str(info["n_sigs"])
    os.environ["CMAP_TEMP_DIR"] = str(temp_dir)

    return info


@pytest.fixture(scope="session")
def client(synthetic_data):
    """FastAPI TestClient（env 变量已在 synthetic_data fixture 中设置）"""
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)
