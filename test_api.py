#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
API 测试脚本
"""

import requests
import json

BASE_URL = "http://localhost:8000"


def test_health():
    """测试健康检查"""
    print("=" * 50)
    print("测试 /health")
    print("=" * 50)

    response = requests.get(f"{BASE_URL}/health")
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")
    print()


def test_extract():
    """测试特征提取接口"""
    print("=" * 50)
    print("测试 /api/v1/extract")
    print("=" * 50)

    payload = {
        "drug": "aspirin",
        "cell_line": "A375"
    }

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/extract",
            json=payload,
            timeout=30
        )
        print(f"状态码: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"药物: {data['drug']}")
            print(f"细胞系: {data['cell_line']}")
            print(f"签名ID: {data['sig_id']}")
            print(f"向量长度: {len(data['vector'])}")
            print(f"向量前5个值: {data['vector'][:5]}")
        else:
            print(f"错误: {response.text}")
    except Exception as e:
        print(f"请求失败: {e}")
    print()


def test_search():
    """测试疾病逆转匹配接口"""
    print("=" * 50)
    print("测试 /api/v1/search")
    print("=" * 50)

    payload = {
        "up_genes": [1, 2, 3, 4, 5],
        "down_genes": [100, 101, 102],
        "top_k": 10
    }

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/search",
            json=payload,
            timeout=300  # 5分钟超时，全库扫描需要较长时间
        )
        print(f"状态码: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"查询上调基因数: {data['query_up_count']}")
            print(f"查询下调基因数: {data['query_down_count']}")
            print(f"返回结果数: {len(data['results'])}")
            print()
            print("Top 5 结果:")
            for r in data['results'][:5]:
                print(f"  Rank {r['rank']}: {r['drug']} ({r['cell_line']}) Score={r['score']:.4f}")
        else:
            print(f"错误: {response.text}")
    except Exception as e:
        print(f"请求失败: {e}")
    print()


if __name__ == "__main__":
    print("CMAP API 测试")
    print("=" * 50)
    print()

    test_health()
    test_extract()
    test_search()
