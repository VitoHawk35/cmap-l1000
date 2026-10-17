#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
跨进程安全的导出 token 存储
基于文件持久化 + 进程内缓存，无需 Redis
"""

import json
import os
import time
import threading
from typing import Optional, Dict

from ..config import TEMP_DIR

EXPORT_DIR = os.path.join(TEMP_DIR, "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)

_DEFAULT_TTL = 300


class ExportStore:
    """导出数据 token 存储，支持多 worker 进程共享"""

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL):
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: Dict[str, dict] = {}

    def _path(self, token: str) -> str:
        return os.path.join(EXPORT_DIR, f"{token}.json")

    def save(self, token: str, payload: dict):
        """保存 token 对应的导出数据"""
        record = {**payload, "created_at": time.time()}
        with self._lock:
            self._cache[token] = record
        try:
            with open(self._path(token), "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"[ExportStore] 保存导出 token 失败 {token}: {e}")

    def load(self, token: str) -> Optional[dict]:
        """读取 token 对应的导出数据，过期返回 None"""
        now = time.time()

        # 1. 先查内存缓存
        with self._lock:
            cached = self._cache.get(token)
        if cached is not None:
            if now - cached.get("created_at", 0) <= self.ttl:
                return cached
            with self._lock:
                self._cache.pop(token, None)

        # 2. 内存未命中，查磁盘
        fpath = self._path(token)
        if not os.path.exists(fpath):
            return None

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        # 3. 检查是否过期
        if now - data.get("created_at", 0) > self.ttl:
            self.delete(token)
            return None

        # 4. 回填内存缓存
        with self._lock:
            self._cache[token] = data
        return data

    def pop(self, token: str) -> Optional[dict]:
        """读取并立即删除 token（一次性下载）"""
        now = time.time()

        # 1. 先查内存缓存并移除
        with self._lock:
            cached = self._cache.pop(token, None)
        if cached is not None:
            if now - cached.get("created_at", 0) <= self.ttl:
                self.delete(token)
                return cached
            return None

        # 2. 内存未命中，查磁盘并删除
        fpath = self._path(token)
        if not os.path.exists(fpath):
            return None

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            os.remove(fpath)
        except Exception:
            return None

        if now - data.get("created_at", 0) > self.ttl:
            return None

        return data

    def delete(self, token: str):
        """删除 token（一次性下载后调用）"""
        with self._lock:
            self._cache.pop(token, None)
        try:
            fpath = self._path(token)
            if os.path.exists(fpath):
                os.remove(fpath)
        except Exception:
            pass

    def cleanup(self):
        """清理过期 token（内存 + 磁盘）"""
        now = time.time()

        # 清理内存缓存
        with self._lock:
            for k in list(self._cache.keys()):
                if now - self._cache[k].get("created_at", 0) > self.ttl:
                    del self._cache[k]

        # 清理磁盘文件
        try:
            for fname in os.listdir(EXPORT_DIR):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(EXPORT_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if now - data.get("created_at", 0) > self.ttl:
                        os.remove(fpath)
                except Exception:
                    pass
        except Exception:
            pass


# 模块级单例
export_store = ExportStore()
