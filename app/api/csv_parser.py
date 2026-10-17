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

# 全局缓存：Entrez ID -> Gene Symbol (反向映射)
_entrez_to_symbol: Dict[int, str] = {}

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


def _load_gene_mapping() -> Tuple[Dict[str, int], Dict[int, str]]:
    """加载基因名映射（Symbol -> Entrez ID，以及反向映射）"""
    global _symbol_to_entrez, _entrez_to_symbol
    if _symbol_to_entrez and _entrez_to_symbol:
        return _symbol_to_entrez, _entrez_to_symbol

    df = pd.read_csv(GENE_INFO_PATH, sep='\t', compression='gzip')

    # 建立双向映射
    for _, row in df.iterrows():
        symbol = str(row['pr_gene_symbol']).upper().strip()
        entrez_id = int(row['pr_gene_id'])
        _symbol_to_entrez[symbol] = entrez_id
        _entrez_to_symbol[entrez_id] = symbol  # 反向映射

    return _symbol_to_entrez, _entrez_to_symbol


@router.post("/parse_csv")
async def parse_csv(
    file: UploadFile = File(...),
    pvalue_threshold: float = Form(0.05),
    top_n: int = Form(50)
) -> Dict[str, Any]:
    """
    解析差异基因 CSV/XLSX 文件，提取上下调基因并映射为 Entrez ID

    Args:
        file: CSV 或 XLSX 文件（需包含 gene/logFC/PValue 列）
        pvalue_threshold: P值阈值（默认0.05）
        top_n: 取前N个上调和前N个下调

    Returns:
        {
            "up_genes": [...], "down_genes": [...],
            "up_symbols": [...], "down_symbols": [...],
            "missing_up": [...], "missing_down": [...],
            "warning": "..." (可选)
        }
    """
    # 服务端校验：top_n 与前端输入框保持一致（10-150）
    if not 10 <= top_n <= 150:
        raise HTTPException(status_code=422, detail="top_n 必须在 10 到 150 之间")

    filename = file.filename.lower()
    is_xlsx = filename.endswith('.xlsx') or filename.endswith('.xls')
    is_csv = filename.endswith('.csv')

    if not (is_csv or is_xlsx):
        raise HTTPException(status_code=400, detail="请上传 CSV 或 XLSX 文件")

    # 读取基因映射
    symbol_to_entrez, entrez_to_symbol = _load_gene_mapping()
    if not symbol_to_entrez:
        raise HTTPException(status_code=500, detail="基因映射字典加载失败")

    try:
        # 读取文件内容
        content = await file.read()

        if is_csv:
            df = pd.read_csv(io.StringIO(content.decode('utf-8')), header=0)
        else:
            # XLSX 格式
            try:
                df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
            except ImportError:
                raise HTTPException(
                    status_code=500,
                    detail="服务器缺少 openpyxl 依赖，无法解析 XLSX 文件，请联系管理员安装：pip install openpyxl"
                )

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

        # 提取上调基因：logFC > 0 的 Top N（logFC最大）
        up_candidates = df[df['logFC'] > 0]
        up_df = up_candidates.head(top_n)

        # 提取下调基因：logFC < 0 的 Top N（logFC最小，即最负）
        down_candidates = df[df['logFC'] < 0]
        down_df = down_candidates.tail(top_n)

        # 记录被过滤掉的零值基因（用于前端提示）
        zero_count = len(df[df['logFC'] == 0])

        # 映射为 Entrez ID，同时记录无法映射的基因
        up_genes: List[int] = []
        down_genes: List[int] = []
        missing_up: List[str] = []
        missing_down: List[str] = []

        for symbol in up_df['gene_symbol']:
            if symbol in symbol_to_entrez:
                up_genes.append(symbol_to_entrez[symbol])
            else:
                missing_up.append(symbol)

        for symbol in down_df['gene_symbol']:
            if symbol in symbol_to_entrez:
                down_genes.append(symbol_to_entrez[symbol])
            else:
                missing_down.append(symbol)

        # 去重并保持顺序
        up_genes = list(dict.fromkeys(up_genes))
        down_genes = list(dict.fromkeys(down_genes))
        missing_up = list(dict.fromkeys(missing_up))
        missing_down = list(dict.fromkeys(missing_down))

        # 获取对应的 Gene Symbol 用于显示（保持相同顺序）
        up_symbols = [entrez_to_symbol.get(gid, str(gid)) for gid in up_genes]
        down_symbols = [entrez_to_symbol.get(gid, str(gid)) for gid in down_genes]

        if not up_genes:
            raise HTTPException(
                status_code=400,
                detail="无法提取上调基因（logFC > 0），请检查数据或降低PValue阈值"
            )

        # 构建结果
        result = {
            "up_genes": up_genes,
            "down_genes": down_genes,
            "up_symbols": up_symbols,
            "down_symbols": down_symbols,
            "missing_up": missing_up,
            "missing_down": missing_down,
        }

        # 下调为空时添加提示
        if not down_genes:
            result["warning"] = "未提取到下调基因（logFC < 0），仅使用上调基因进行搜索"
        elif zero_count > 0:
            result["warning"] = f"有 {zero_count} 个基因 logFC = 0，已排除"

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
        all_missing = missing_up + missing_down
        if all_missing:
            unique_missing = list(set(all_missing))[:10]  # 最多显示10个
            if 'warning' in result:
                result['warning'] += f"；以下基因无法映射：{', '.join(unique_missing)}"
            else:
                result['warning'] = f"以下基因无法映射（可能输入有误）：{', '.join(unique_missing)}"

        return result

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="文件为空")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"文件解析错误：{str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败：{str(e)}")


@router.post("/convert_to_ids")
async def convert_to_ids(symbols: List[str]) -> Dict[str, Any]:
    """
    将 Gene Symbol 列表转换为 Entrez ID 列表

    用于手动输入场景下将基因名转换为计算用的 ID
    """
    symbol_to_entrez, _ = _load_gene_mapping()

    ids = []
    missing = []

    for symbol in symbols:
        symbol_clean = symbol.strip().upper()
        gid = symbol_to_entrez.get(symbol_clean)
        if gid:
            ids.append(gid)
        else:
            missing.append(symbol)

    return {
        "ids": ids,
        "missing": missing,
        "total": len(symbols),
        "mapped": len(ids)
    }
    """
    将 Entrez ID 列表转换为 Gene Symbol 列表

    用于手动输入场景下显示基因名称
    """
    _, entrez_to_symbol = _load_gene_mapping()

    symbols = []
    missing = []

    for gid in gene_ids:
        symbol = entrez_to_symbol.get(gid)
        if symbol:
            symbols.append(symbol)
        else:
            symbols.append(str(gid))  # 找不到时显示数字
            missing.append(str(gid))

    return {
        "symbols": symbols,
        "missing": missing,
        "total": len(gene_ids),
        "mapped": len(gene_ids) - len(missing)
    }
