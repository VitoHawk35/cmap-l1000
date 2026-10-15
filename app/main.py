#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FastAPI 应用入口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import os

INDEX_HTML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html"
)
ECHARTS_JS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "echarts.min.js"
)

from .api.extract import router as extract_router
from .api.search import router as search_router
from .api.csv_parser import router as csv_parser_router
from .api.export import router as export_router
from .api.wtcs_search import router as wtcs_search_router
from .api.export_wtcs import router as export_wtcs_router
from .api.export_data import router as export_data_router
from .api.tau_search import router as tau_search_router

# 创建 FastAPI 应用
app = FastAPI(
    title="CMAP L1000 API",
    description="CMAP L1000 基因表达数据检索服务",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(extract_router, prefix="/api/v1", tags=["特征提取"])
app.include_router(search_router, prefix="/api/v1", tags=["疾病逆转匹配"])
app.include_router(wtcs_search_router, prefix="/api/v1", tags=["WTCS算法搜索"])
app.include_router(tau_search_router, prefix="/api/v1", tags=["Tau分数搜索(完整后处理)"])
app.include_router(csv_parser_router, prefix="/api/v1", tags=["CSV解析"])
app.include_router(export_router, prefix="/api/v1", tags=["结果导出"])
app.include_router(export_wtcs_router, prefix="/api/v1", tags=["WTCS结果导出"])
app.include_router(export_data_router, prefix="/api/v1", tags=["通用结果导出"])


@app.get("/", include_in_schema=False)
async def root():
    """托管前端页面（同源部署，避免自签名证书跨端口信任问题）"""
    return FileResponse(INDEX_HTML_PATH)


@app.get("/echarts.min.js", include_in_schema=False)
async def echarts_js():
    """本地化 ECharts（服务器在内网，不从 CDN 加载）"""
    return FileResponse(ECHARTS_JS_PATH, media_type="application/javascript")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}
