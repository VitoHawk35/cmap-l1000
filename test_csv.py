#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CSV 解析接口测试脚本
"""

import requests
import os

# 配置
BASE_URL = "http://localhost:8000"
CSV_FILE = "cmap_data/implantedvscultured0429_edgeR_diff_gene.csv"


def test_health():
    """测试服务是否运行"""
    print("=" * 50)
    print("测试1: 健康检查")
    print("=" * 50)
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        print("\n服务可能未启动，请先运行: python run.py")
        return False


def test_csv_parser():
    """测试 CSV 解析接口"""
    print("\n" + "=" * 50)
    print("测试2: CSV 解析接口")
    print("=" * 50)

    if not os.path.exists(CSV_FILE):
        print(f"错误: 找不到文件 {CSV_FILE}")
        return

    print(f"上传文件: {CSV_FILE}")
    print(f"文件大小: {os.path.getsize(CSV_FILE) / 1024:.2f} KB")

    try:
        with open(CSV_FILE, 'rb') as f:
            files = {'file': ('test.csv', f, 'text/csv')}
            data = {
                'pvalue_threshold': 0.05,
                'top_n': 50
            }

            print("\n发送请求...")
            response = requests.post(
                f"{BASE_URL}/api/v1/parse_csv",
                files=files,
                data=data,
                timeout=60
            )

        print(f"状态码: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"\n成功!")
            print(f"上调基因数: {len(result.get('up_genes', []))}")
            print(f"下调基因数: {len(result.get('down_genes', []))}")
            print(f"上调基因前5个: {result.get('up_genes', [])[:5]}")
            print(f"下调基因前5个: {result.get('down_genes', [])[:5]}")
            if 'warning' in result:
                print(f"警告: {result['warning']}")
        else:
            print(f"\n错误!")
            try:
                error = response.json()
                print(f"错误详情: {error}")
            except:
                print(f"响应内容: {response.text[:500]}")

    except requests.exceptions.ConnectionError:
        print(f"\n连接失败! 请检查:")
        print("1. 服务是否已启动 (python run.py)")
        print("2. 端口是否正确 (默认8000)")
    except Exception as e:
        print(f"\n错误: {type(e).__name__}: {e}")


def test_gene_mapping():
    """测试基因映射是否加载正确"""
    print("\n" + "=" * 50)
    print("测试3: 基因映射字典")
    print("=" * 50)

    try:
        import pandas as pd
        from app.config import GENE_INFO_PATH

        df = pd.read_csv(GENE_INFO_PATH, sep='\t', compression='gzip')
        print(f"基因信息文件行数: {len(df)}")
        print(f"列名: {df.columns.tolist()}")

        # 测试几个基因
        test_genes = ['IL12RB2', 'GBP5', 'VCAM1', 'TP53', 'GAPDH']
        symbol_to_entrez = {}
        for _, row in df.iterrows():
            symbol = str(row['pr_gene_symbol']).upper().strip()
            entrez_id = int(row['pr_gene_id'])
            symbol_to_entrez[symbol] = entrez_id

        print(f"\n映射字典大小: {len(symbol_to_entrez)}")
        print("\n测试基因映射:")
        for gene in test_genes:
            entrez = symbol_to_entrez.get(gene)
            status = "✓" if entrez else "✗"
            print(f"  {status} {gene} -> {entrez if entrez else '未找到'}")

    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    print("CMAP L1000 CSV 解析接口测试")
    print("=" * 50)

    # 先测试健康检查
    if test_health():
        # 再测试基因映射
        test_gene_mapping()
        # 最后测试 CSV 解析
        test_csv_parser()
    else:
        print("\n服务未运行，跳过后续测试")
