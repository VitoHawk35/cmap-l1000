#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LINCS L1000 数据完整性防线（D1 · 防线1：启动时逐 ID 比对 / 指纹比对）。

⚠️ 本文件在两处各有一份，内容必须保持完全一致，修改需同步：
    - LMNA      : backend/lincs_integrity.py
    - cmap-l1000: app/core/lincs_integrity.py

背景
----
fast_matrix.npy 本身没有行列名，靠 row_gene_ids.csv / col_sig_ids.csv 两份
"花名册"对应基因与实验。花名册错一位，所有结果张冠李戴且程序不报错。
本模块在数据加载时强制校验花名册与矩阵：

  - gctx 模式        ：直接读取 GCTX 的 0/META/ROW/id 与 0/META/COL/id，
                       与花名册逐个 ID 比对；
  - fingerprint 模式 ：与 scripts/fix_col_names.py --write-fingerprint 写出的
                       integrity.json 比对（花名册 sha256、矩阵形状、
                       3 列抽样数值哈希）。不依赖 23GB GCTX，是默认模式；
  - off              ：关闭检查（仅供测试），启用时打 WARNING 日志。

模式由环境变量 LINCS_INTEGRITY_MODE=gctx|fingerprint|off 选择，默认 fingerprint。

任何一处不一致都抛 RuntimeError 拒绝启动；错误信息给出第一个不一致的
位置和修复命令。文件末尾多余的空行按约定容忍，但会打 WARNING 日志，
绝不静默。

兼容 Python 3.8（cmap-l1000 运行时为 3.8）：禁止 list[str] / X | None 等新语法。
"""

import hashlib
import json
import logging
import os
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("lincs_integrity")

# 环境变量与默认值
MODE_ENV = "LINCS_INTEGRITY_MODE"
GCTX_PATH_ENV = "LINCS_GCTX_PATH"
DEFAULT_MODE = "fingerprint"
VALID_MODES = ("gctx", "fingerprint", "off")

FINGERPRINT_FILENAME = "integrity.json"
FINGERPRINT_FORMAT_VERSION = 1
DEFAULT_GCTX_NAME = "GSE92742_Broad_LINCS_Level5_COMPZ.MODZ_n473647x12328.gctx"

ROW_ID_COLUMN = "gene_id"
COL_ID_COLUMN = "sig_id"


# ---------------------------------------------------------------------------
# 模式选择
# ---------------------------------------------------------------------------

def get_mode(mode: Optional[str] = None) -> str:
    """解析完整性检查模式；非法取值按配置错误处理（fail safe）。"""
    resolved = (mode or os.getenv(MODE_ENV) or DEFAULT_MODE).strip().lower()
    if resolved not in VALID_MODES:
        raise RuntimeError(
            "%s=%r 非法：可选值为 %s" % (MODE_ENV, resolved, "/".join(VALID_MODES))
        )
    return resolved


# ---------------------------------------------------------------------------
# 花名册读取与逐 ID 比对
# ---------------------------------------------------------------------------

def read_roster_ids(csv_path: str, column: str,
                    label: Optional[str] = None) -> List[str]:
    """读取花名册 ID 列（转字符串）。

    文件末尾多余的空行按约定容忍（pandas 默认跳过），但打 WARNING 日志，
    不静默。
    """
    name = label or os.path.basename(csv_path)
    if not os.path.exists(csv_path):
        raise RuntimeError("花名册文件不存在: %s" % csv_path)

    df = pd.read_csv(csv_path)
    if column not in df.columns:
        raise RuntimeError(
            "%s 缺少列 %r（实际列：%s）" % (name, column, list(df.columns))
        )

    # 末尾空行检测：容忍但告警（V-D1a 约定行为）
    try:
        with open(csv_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            tail = b""
            if size:
                f.seek(max(0, size - 4096))
                tail = f.read()
        stripped = tail.rstrip(b"\r\n")
        if tail[len(stripped):].count(b"\n") > 1:
            logger.warning(
                "%s 文件末尾存在多余空行，已按约定忽略（比对不受影响）", name
            )
    except OSError:
        pass

    return df[column].astype(str).tolist()


def first_mismatch(file_ids: Sequence[str], truth_ids: Sequence[str]) -> Optional[int]:
    """返回第一个不一致的位置（0 基）；全部一致返回 None。"""
    n = min(len(file_ids), len(truth_ids))
    for i in range(n):
        if file_ids[i] != truth_ids[i]:
            return i
    if len(file_ids) != len(truth_ids):
        return n
    return None


def repair_hint(data_dir: str) -> str:
    """统一的诊断/修复命令提示。"""
    return (
        "诊断第一个不一致位置：python scripts/fix_col_names.py "
        "--data-dir {d} --check；"
        "修复花名册：python scripts/fix_col_names.py "
        "--data-dir {d} --in-place --fix-rows；"
        "修复后重新生成指纹：python scripts/fix_col_names.py "
        "--data-dir {d} --check --write-fingerprint"
    ).format(d=data_dir)


def assert_ids_equal(name: str, file_ids: Sequence[str],
                     truth_ids: Sequence[str], data_dir: str,
                     truth_desc: str) -> None:
    """逐 ID 比对；任何不一致抛 RuntimeError（含第一个不一致位置与修复命令）。"""
    if len(file_ids) != len(truth_ids):
        raise RuntimeError(
            "%s 行数 %d 与%s行数 %d 不一致（花名册可能被增删过行）。%s"
            % (name, len(file_ids), truth_desc, len(truth_ids),
               repair_hint(data_dir))
        )
    idx = first_mismatch(file_ids, truth_ids)
    if idx is not None:
        raise RuntimeError(
            "%s 第 %d 行（0 基）与%s不一致：文件=%r，应为 %r。"
            "按此花名册取数会张冠李戴。%s"
            % (name, idx, truth_desc, file_ids[idx], truth_ids[idx],
               repair_hint(data_dir))
        )


# ---------------------------------------------------------------------------
# 指纹
# ---------------------------------------------------------------------------

def hash_id_list(ids: Sequence[str]) -> str:
    """ID 列表的 sha256（顺序敏感）。"""
    h = hashlib.sha256()
    h.update("\n".join(str(x) for x in ids).encode("utf-8"))
    return h.hexdigest()


def sample_column_indices(n_cols: int) -> List[int]:
    """3 列抽样位置：首/中/末（去重、升序）。"""
    if n_cols <= 0:
        return []
    return sorted({0, n_cols // 2, n_cols - 1})


def _matrix_shape_from_rosters(n_rows: int, n_cols: int,
                               matrix_path: str) -> Tuple[int, int]:
    """由花名册行数推矩阵形状，并用文件字节数交叉验证。"""
    if not os.path.exists(matrix_path):
        raise RuntimeError("矩阵文件不存在: %s" % matrix_path)
    expected_bytes = n_rows * n_cols * 4  # float32 裸 memmap
    actual = os.path.getsize(matrix_path)
    if actual != expected_bytes:
        raise RuntimeError(
            "矩阵文件 %s 大小 %d 字节与花名册推出的形状 (%d, %d) 不符"
            "（应为 %d 字节）——矩阵与花名册不是同一份数据。"
            % (matrix_path, actual, n_rows, n_cols, expected_bytes)
        )
    return n_rows, n_cols


def build_fingerprint(matrix_path: str,
                      row_csv_path: str,
                      col_csv_path: str,
                      row_id_column: str = ROW_ID_COLUMN,
                      col_id_column: str = COL_ID_COLUMN,
                      row_ids: Optional[Sequence[str]] = None,
                      col_ids: Optional[Sequence[str]] = None) -> Dict:
    """根据当前花名册与矩阵构建指纹 dict（不校验正确性，只描述现状）。"""
    if row_ids is None:
        row_ids = read_roster_ids(row_csv_path, row_id_column)
    else:
        row_ids = [str(x) for x in row_ids]
    if col_ids is None:
        col_ids = read_roster_ids(col_csv_path, col_id_column)
    else:
        col_ids = [str(x) for x in col_ids]

    shape = _matrix_shape_from_rosters(len(row_ids), len(col_ids), matrix_path)

    matrix = np.memmap(matrix_path, dtype="float32", mode="r", shape=shape)
    try:
        samples = []
        for idx in sample_column_indices(shape[1]):
            column = np.asarray(matrix[:, idx])
            samples.append({
                "index": int(idx),
                "id": str(col_ids[idx]),
                "values_sha256": hashlib.sha256(
                    np.ascontiguousarray(column, dtype=np.float32).tobytes()
                ).hexdigest(),
            })
    finally:
        del matrix  # Windows 下释放文件句柄

    return {
        "format_version": FINGERPRINT_FORMAT_VERSION,
        "created_by": "lincs_integrity.py",
        "matrix_file": os.path.basename(matrix_path),
        "matrix_shape": [int(shape[0]), int(shape[1])],
        "matrix_bytes": int(shape[0] * shape[1] * 4),
        "row_count": int(shape[0]),
        "col_count": int(shape[1]),
        "row_ids_sha256": hash_id_list(row_ids),
        "col_ids_sha256": hash_id_list(col_ids),
        "column_samples": samples,
    }


def write_fingerprint(fingerprint: Dict, path: str) -> str:
    """原子写出 integrity.json。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".integrity-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def load_fingerprint(path: str) -> Dict:
    if not os.path.exists(path):
        raise RuntimeError("指纹文件不存在: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        fp = json.load(f)
    if fp.get("format_version") != FINGERPRINT_FORMAT_VERSION:
        raise RuntimeError(
            "指纹文件 %s 的 format_version=%r 不受支持（期望 %d）"
            % (path, fp.get("format_version"), FINGERPRINT_FORMAT_VERSION)
        )
    return fp


def _verify_roster_against_fingerprint(name: str, csv_path: str, column: str,
                                       expected_count: int,
                                       expected_sha: str,
                                       data_dir: str) -> List[str]:
    ids = read_roster_ids(csv_path, column, label=name)
    if len(ids) != expected_count:
        raise RuntimeError(
            "%s 行数 %d 与指纹记录 %d 不一致（花名册被增删过行）。%s"
            % (name, len(ids), expected_count, repair_hint(data_dir))
        )
    actual_sha = hash_id_list(ids)
    if actual_sha != expected_sha:
        raise RuntimeError(
            "%s 与 integrity.json 指纹不一致（sha256 实际=%s，指纹=%s）——"
            "花名册顺序已被改动，按此映射取数会张冠李戴。%s"
            % (name, actual_sha[:16], expected_sha[:16], repair_hint(data_dir))
        )
    return ids


def verify_fingerprint(matrix_path: str,
                       row_csv_path: str,
                       col_csv_path: str,
                       fingerprint: Dict,
                       row_id_column: str = ROW_ID_COLUMN,
                       col_id_column: str = COL_ID_COLUMN,
                       row_label: Optional[str] = None,
                       col_label: Optional[str] = None) -> None:
    """把花名册与矩阵同指纹比对；任何不一致抛 RuntimeError。"""
    data_dir = os.path.dirname(os.path.abspath(matrix_path))
    row_name = row_label or os.path.basename(row_csv_path)
    col_name = col_label or os.path.basename(col_csv_path)

    # 1. 矩阵文件大小（防同形状替换之外的大小变化）
    if not os.path.exists(matrix_path):
        raise RuntimeError("矩阵文件不存在: %s" % matrix_path)
    expected_bytes = int(fingerprint["matrix_bytes"])
    actual_bytes = os.path.getsize(matrix_path)
    if actual_bytes != expected_bytes:
        raise RuntimeError(
            "矩阵文件 %s 大小 %d 字节与指纹记录 %d 不一致——矩阵已被替换。%s"
            % (matrix_path, actual_bytes, expected_bytes, repair_hint(data_dir))
        )

    # 2. 花名册逐 hash 比对
    _verify_roster_against_fingerprint(
        row_name, row_csv_path, row_id_column,
        int(fingerprint["row_count"]), fingerprint["row_ids_sha256"], data_dir,
    )
    col_ids = _verify_roster_against_fingerprint(
        col_name, col_csv_path, col_id_column,
        int(fingerprint["col_count"]), fingerprint["col_ids_sha256"], data_dir,
    )

    # 3. 3 列抽样数值哈希（防矩阵被换成同形状的另一个文件）
    shape = tuple(int(x) for x in fingerprint["matrix_shape"])
    matrix = np.memmap(matrix_path, dtype="float32", mode="r", shape=shape)
    try:
        for sample in fingerprint["column_samples"]:
            idx = int(sample["index"])
            if col_ids[idx] != sample["id"]:
                raise RuntimeError(
                    "抽样列 %d 的 sig_id=%r 与指纹记录 %r 不一致。%s"
                    % (idx, col_ids[idx], sample["id"], repair_hint(data_dir))
                )
            column = np.asarray(matrix[:, idx])
            actual = hashlib.sha256(
                np.ascontiguousarray(column, dtype=np.float32).tobytes()
            ).hexdigest()
            if actual != sample["values_sha256"]:
                raise RuntimeError(
                    "矩阵第 %d 列（%s）的抽样数值哈希与指纹不一致"
                    "（实际=%s，指纹=%s）——矩阵已被替换为同形状的另一个文件。%s"
                    % (idx, sample["id"], actual[:16],
                       sample["values_sha256"][:16], repair_hint(data_dir))
                )
    finally:
        del matrix


# ---------------------------------------------------------------------------
# GCTX 逐 ID 比对
# ---------------------------------------------------------------------------

def read_gctx_meta_ids(gctx_path: str) -> Tuple[List[str], List[str]]:
    """读取 GCTX 的 0/META/ROW/id 与 0/META/COL/id（懒加载 h5py）。"""
    if not os.path.exists(gctx_path):
        raise RuntimeError(
            "GCTX 文件不存在: %s。gctx 模式需要原始 GCTX；"
            "可用 %s 指定路径，或改用 fingerprint 模式。"
            % (gctx_path, GCTX_PATH_ENV)
        )
    try:
        import h5py
    except ImportError:
        raise RuntimeError(
            "gctx 模式需要 h5py 读取 GCTX 元数据；"
            "当前环境无 h5py，请安装或改用 fingerprint 模式。"
        )

    def _decode(values):
        return [
            v.decode() if isinstance(v, bytes) else str(v) for v in values
        ]

    with h5py.File(gctx_path, "r") as f:
        row_ids = _decode(f["0/META/ROW/id"][:])
        col_ids = _decode(f["0/META/COL/id"][:])
    return row_ids, col_ids


def verify_against_gctx(gctx_path: str,
                        matrix_path: str,
                        row_csv_path: str,
                        col_csv_path: str,
                        row_id_column: str = ROW_ID_COLUMN,
                        col_id_column: str = COL_ID_COLUMN,
                        row_label: Optional[str] = None,
                        col_label: Optional[str] = None) -> None:
    """花名册与 GCTX 元数据逐 ID 比对；矩阵大小与 GCTX 维度交叉验证。"""
    data_dir = os.path.dirname(os.path.abspath(matrix_path))
    row_name = row_label or os.path.basename(row_csv_path)
    col_name = col_label or os.path.basename(col_csv_path)

    truth_rows, truth_cols = read_gctx_meta_ids(gctx_path)

    file_rows = read_roster_ids(row_csv_path, row_id_column, label=row_name)
    file_cols = read_roster_ids(col_csv_path, col_id_column, label=col_name)

    assert_ids_equal(row_name, file_rows, truth_rows, data_dir, "GCTX 0/META/ROW/id")
    assert_ids_equal(col_name, file_cols, truth_cols, data_dir, "GCTX 0/META/COL/id")

    _matrix_shape_from_rosters(len(truth_rows), len(truth_cols), matrix_path)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

def check_startup(matrix_path: str,
                  row_csv_path: str,
                  col_csv_path: str,
                  row_id_column: str = ROW_ID_COLUMN,
                  col_id_column: str = COL_ID_COLUMN,
                  mode: Optional[str] = None,
                  gctx_path: Optional[str] = None,
                  fingerprint_path: Optional[str] = None,
                  row_label: Optional[str] = None,
                  col_label: Optional[str] = None) -> Dict:
    """启动时完整性检查（防线1）。

    按 LINCS_INTEGRITY_MODE（默认 fingerprint）分派：
      - off        ：打 WARNING 后直接放行（仅供测试）；
      - fingerprint：与 integrity.json 比对；
      - gctx       ：与 GCTX 元数据逐 ID 比对。

    Returns:
        {"mode": ..., "checked": [...]} 报告 dict。

    Raises:
        RuntimeError: 任何不一致，拒绝启动。
    """
    resolved = get_mode(mode)
    data_dir = os.path.dirname(os.path.abspath(matrix_path))

    if resolved == "off":
        logger.warning(
            "%s=off：LINCS 数据完整性检查已关闭，仅供测试使用；"
            "花名册错位将不会被发现", MODE_ENV
        )
        return {"mode": resolved, "checked": []}

    if resolved == "gctx":
        gctx = (
            gctx_path
            or os.getenv(GCTX_PATH_ENV)
            or os.path.join(data_dir, DEFAULT_GCTX_NAME)
        )
        verify_against_gctx(
            gctx, matrix_path, row_csv_path, col_csv_path,
            row_id_column=row_id_column, col_id_column=col_id_column,
            row_label=row_label, col_label=col_label,
        )
        logger.info("LINCS 完整性检查通过（gctx 模式，逐 ID 比对）")
        return {"mode": resolved, "checked": ["row_ids", "col_ids", "matrix_shape"]}

    # fingerprint（默认）
    fp_path = fingerprint_path or os.path.join(data_dir, FINGERPRINT_FILENAME)
    if not os.path.exists(fp_path):
        raise RuntimeError(
            "未找到完整性指纹文件 %s。请先在数据修复后生成指纹："
            "python scripts/fix_col_names.py --data-dir %s --check "
            "--write-fingerprint；或设置 %s=gctx 直接与 GCTX 逐 ID 比对。"
            % (fp_path, data_dir, MODE_ENV)
        )
    fp = load_fingerprint(fp_path)
    verify_fingerprint(
        matrix_path, row_csv_path, col_csv_path, fp,
        row_id_column=row_id_column, col_id_column=col_id_column,
        row_label=row_label, col_label=col_label,
    )
    logger.info("LINCS 完整性检查通过（fingerprint 模式：%s）", fp_path)
    return {
        "mode": resolved,
        "checked": ["row_ids", "col_ids", "matrix_shape", "column_samples"],
    }
