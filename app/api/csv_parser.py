#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CSV 差异基因文件解析接口
自动解析生信软件输出的 CSV，提取上下调基因并映射为 Entrez ID
"""

import gzip
import io
from typing import List, Dict, Tuple, Any

import pandas as pd
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from ..config import GENE_INFO_PATH

router = APIRouter()

# 全局缓存：Gene Symbol -> Entrez ID
_symbol_to_entrez: Dict[str, int] = {}

# 可能的列名变体（小写用于匹配）
_COLUMN_NAME_VARIANTS = {
    'gene': ['gene', 'genes', 'gene_symbol', 'gene symbol', 'symbol', 'symbols',
             'genename', 'gene_name', 'feature', 'features', 'row.names', ''],
    'logfc': ['logfc', 'log2foldchange', 'avg_log2fc', 'avg_logfc', 'log_fold_change',
              'fc', 'foldchange', 'fold_change', 'log2fc'],
    'pvalue': ['pvalue', 'p_val', 'pval', 'p.value', 'p_value', 'padj', 'adj.p.val',
               'adj_p_val', 'fdr', 'fdr_value', 'qvalue', 'q_val', 'q_value']
}


def _find_column(df: pd.DataFrame, col_type: str) -> str:
    """
    根据列类型查找匹配的列名

    优先按列名匹配，找不到则返回None
    """
    variants = _COLUMN_NAME_VARIANTS.get(col_type, [])
    df_columns_lower = {c.lower().strip(): c for c in df.columns}

    for variant in variants:
        if variant in df_columns_lower:
            return df_columns_lower[variant]
    return None


def _extract_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    提取所需的三列（基因、logFC、PValue）

    策略：
    1. 优先按列名匹配
    2. 列名匹配失败则使用默认列索引 [1, 2, 4]
    """
    # 尝试按列名匹配
    gene_col = _find_column(df, 'gene')
    logfc_col = _find_column(df, 'logfc')
    pvalue_col = _find_column(df, 'pvalue')

    # 如果三列都通过列名匹配成功
    if gene_col and logfc_col and pvalue_col:
        result = df[[gene_col, logfc_col, pvalue_col]].copy()
        result.columns = ['gene_symbol', 'logFC', 'PValue']
        return result

    # 否则使用默认列索引策略（保持原有行为）
    if df.shape[1] < 5:
        raise ValueError(f"CSV 文件列数不足（需要5列，实际{df.shape[1]}列），且无法识别所需列名")

    result = df.iloc[:, [1, 2, 4]].copy()
    result.columns = ['gene_symbol', 'logFC', 'PValue']
    return result


def _load_gene_mapping() -> Dict[str, int]:
    """加载基因名映射（Symbol -> Entrez ID）"""
    global _symbol_to_entrez
    if _symbol_to_entrez:
        return _symbol_to_entrez

    df = pd.read_csv(GENE_INFO_PATH, sep='\t', compression='gzip')

    # 建立映射：pr_gene_symbol -> pr_gene_id
    for _, row in df.iterrows():
        symbol = str(row['pr_gene_symbol']).upper().strip()
        entrez_id = int(row['pr_gene_id'])
        _symbol_to_entrez[symbol] = entrez_id

    return _symbol_to_entrez


@router.post("/parse_csv")
async def parse_csv(
    file: UploadFile = File(...),
    pvalue_threshold: float = Form(0.05),
    top_n: int = Form(50)
) -> Dict[str, Any]:
    """
    解析差异基因 CSV 文件，提取上下调基因并映射为 Entrez ID

    Args:
        file: CSV 文件（第1列基因名，第2列logFC，第4列PValue）
        pvalue_threshold: P值阈值（默认0.05）
        top_n: 取前N个上调和前N个下调

    Returns:
        {"up_genes": [...], "down_genes": [...], "warning": "..." (可选)}
    """
    # 检查文件类型
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")

    # 读取基因映射
    symbol_to_entrez = _load_gene_mapping()
    if not symbol_to_entrez:
        raise HTTPException(status_code=500, detail="基因映射字典加载失败")

    try:
        # 读取 CSV 文件
        content = await file.read()
        df = pd.read_csv(io.StringIO(content.decode('utf-8')), header=0)

        # 如果存在 group1 列，只取第一个组的对比数据（避免重复）
        if 'group1' in df.columns:
            groups = df['group1'].unique()
            if len(groups) > 1:
                selected_group = groups[0]  # 取第一个组
                df = df[df['group1'] == selected_group].copy()
                print(f"[CSV Parser] 多组数据检测到，仅使用 group1={selected_group} 的数据")

        # 提取所需列（优先按列名匹配，失败则使用默认列索引）
        df = _extract_columns(df)

        # 清理数据
        df['gene_symbol'] = df['gene_symbol'].astype(str).str.upper().str.strip()
        df['logFC'] = pd.to_numeric(df['logFC'], errors='coerce')
        df['PValue'] = pd.to_numeric(df['PValue'], errors='coerce')

        # 过滤无效数据
        df = df.dropna(subset=['logFC', 'PValue'])
        df = df[df['PValue'] < pvalue_threshold]

        if len(df) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"没有满足条件的基因（PValue < {pvalue_threshold}）"
            )

        # 按 logFC 降序排序
        df = df.sort_values('logFC', ascending=False).reset_index(drop=True)

        # 提取 Top N 上调（logFC最大）和 Top N 下调（logFC最小）
        up_df = df.head(top_n)
        down_df = df.tail(top_n)

        # 映射为 Entrez ID
        up_genes: List[int] = []
        down_genes: List[int] = []
        missing_symbols: List[str] = []

        for symbol in up_df['gene_symbol']:
            if symbol in symbol_to_entrez:
                up_genes.append(symbol_to_entrez[symbol])
            else:
                missing_symbols.append(symbol)

        for symbol in down_df['gene_symbol']:
            if symbol in symbol_to_entrez:
                down_genes.append(symbol_to_entrez[symbol])
            else:
                missing_symbols.append(symbol)

        # 去重并保持顺序
        up_genes = list(dict.fromkeys(up_genes))
        down_genes = list(dict.fromkeys(down_genes))

        if not up_genes and not down_genes:
            raise HTTPException(
                status_code=400,
                detail="无法识别任何有效的基因ID，请检查基因名称是否正确"
            )

        # 构建结果
        result = {
            "up_genes": up_genes,
            "down_genes": down_genes,
        }

        # 检查上调和下调基因是否有重叠
        overlap = set(up_genes) & set(down_genes)
        if overlap:
            # 从两个列表中都移除重叠的基因
            result["up_genes"] = [g for g in up_genes if g not in overlap]
            result["down_genes"] = [g for g in down_genes if g not in overlap]
            overlap_warning = f"上调和下调基因存在 {len(overlap)} 个重叠项，已自动移除"
            if 'warning' in result:
                result['warning'] += f"；{overlap_warning}"
            else:
                result['warning'] = overlap_warning

        # 如果有未映射的基因，添加警告信息
        if missing_symbols:
            unique_missing = list(set(missing_symbols))[:10]  # 最多显示10个
            if 'warning' in result:
                result['warning'] += f"；以下基因无法映射：{', '.join(unique_missing)}"
            else:
                result['warning'] = f"以下基因无法映射（可能输入有误）：{', '.join(unique_missing)}"

        return result

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="CSV 文件为空")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"CSV 解析错误：{str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败：{str(e)}")
