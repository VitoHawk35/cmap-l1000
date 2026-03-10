#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CMAP L1000 API 启动脚本

使用方法:
    python run.py

或者使用 uvicorn 直接启动:
    uvicorn app.main:app --reload
"""

import sys
import uvicorn

from app.config import API_HOST, API_PORT


def main():
    """启动 FastAPI 服务"""
    print("=" * 60)
    print("CMAP L1000 API 服务")
    print("=" * 60)
    print(f"服务地址: http://{API_HOST}:{API_PORT}")
    print(f"API 文档: http://{API_HOST}:{API_PORT}/docs")
    print("=" * 60)
    print()

    uvicorn.run(
        "app.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        workers=1,  # memmap 不共享，单进程模式
        log_level="info"
    )


if __name__ == "__main__":
    main()
