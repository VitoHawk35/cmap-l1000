#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通用搜索结果导出接口
前端直接把结果数据提交过来，后端打包成 ZIP 返回一次性下载链接
避免前端 JSZip 生成 blob 在某些安全环境下被拦截
"""

import io
import zipfile
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import pandas as pd

from ..core.export_store import export_store

router = APIRouter()


class ExportDataRequest(BaseModel):
    algorithm: str          # 'cosine' | 'wtcs' | 'tau'
    top_results: list
    bottom_results: list


class ExportTokenResponse(BaseModel):
    token: str
    download_url: str


def _results_to_csv(results: list, algorithm: str) -> str:
    """把结果列表转成 CSV 字符串"""
    if algorithm == "tau":
        headers = [
            "rank", "pert_iname", "pert_type", "tau_score",
            "summary_ncs", "best_wtcs", "cell_count", "best_cell_id", "best_dose", "is_touchstone"
        ]
        data = []
        for r in results:
            data.append({
                "rank": r.get("rank", ""),
                "pert_iname": r.get("pert_iname", r.get("drug", "")),
                "pert_type": r.get("pert_type", ""),
                "tau_score": r.get("tau_score", r.get("score", "")),
                "summary_ncs": r.get("summary_ncs", ""),
                "best_wtcs": r.get("best_wtcs", ""),
                "cell_count": r.get("cell_count", ""),
                "best_cell_id": r.get("best_cell_id", ""),
                "best_dose": r.get("best_dose", ""),
                "is_touchstone": "1" if r.get("is_touchstone") else "0",
            })
    else:
        score_key = "wtcs_score" if algorithm == "wtcs" else "cosine_score"
        headers = ["rank", "sig_id", "drug", "cell_line", "dose", "pert_type", score_key]
        data = []
        for r in results:
            data.append({
                "rank": r.get("rank", ""),
                "sig_id": r.get("sig_id", ""),
                "drug": r.get("drug", r.get("pert_iname", "")),
                "cell_line": r.get("cell_line", ""),
                "dose": r.get("dose", ""),
                "pert_type": r.get("pert_type", ""),
                score_key: r.get("score", ""),
            })

    df = pd.DataFrame(data, columns=headers)
    return df.to_csv(index=False, encoding="utf-8-sig")


@router.post("/export_data", response_model=ExportTokenResponse)
def export_data(request: ExportDataRequest):
    """
    提交导出数据，返回一次性下载 token
    """
    token = str(uuid.uuid4())
    export_store.cleanup()
    export_store.save(
        token,
        {
            "algorithm": request.algorithm,
            "top_results": request.top_results,
            "bottom_results": request.bottom_results,
        },
    )

    return ExportTokenResponse(
        token=token, download_url=f"/api/v1/export_data/{token}"
    )


@router.get("/export_data/{token}")
def download_export(token: str):
    """
    用 token 下载 ZIP 文件（一次性有效）
    """
    export_store.cleanup()
    data = export_store.pop(token)
    if data is None:
        raise HTTPException(status_code=404, detail="下载链接已过期或不存在")

    algorithm = data["algorithm"]
    top_csv = _results_to_csv(data["top_results"], algorithm)
    bottom_csv = _results_to_csv(data["bottom_results"], algorithm)

    if algorithm == "tau":
        top_name = "top_reversals_tau.csv"
        bottom_name = "bottom_matches_tau.csv"
        zip_name = "cmap_tau_results.zip"
    elif algorithm == "wtcs":
        top_name = "top_reversals_wtcs.csv"
        bottom_name = "bottom_matches_wtcs.csv"
        zip_name = "cmap_wtcs_results.zip"
    else:
        top_name = "top_reversals.csv"
        bottom_name = "bottom_matches.csv"
        zip_name = "cmap_search_results.zip"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(top_name, top_csv)
        zf.writestr(bottom_name, bottom_csv)

    zip_buffer.seek(0)
    content_length = len(zip_buffer.getvalue())

    return StreamingResponse(
        zip_buffer,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=\"{zip_name}\"",
            "Content-Length": str(content_length),
        }
    )
