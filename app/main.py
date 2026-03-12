#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FastAPI 应用入口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.extract import router as extract_router
from .api.search import router as search_router
from .api.csv_parser import router as csv_parser_router
from .api.export import router as export_router
from .api.wtcs_search import router as wtcs_search_router
from .api.export_wtcs import router as export_wtcs_router

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
app.include_router(csv_parser_router, prefix="/api/v1", tags=["CSV解析"])
app.include_router(export_router, prefix="/api/v1", tags=["结果导出"])
app.include_router(export_wtcs_router, prefix="/api/v1", tags=["WTCS结果导出"])


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "CMAP L1000 API 服务运行中",
        "docs": "/docs",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}
