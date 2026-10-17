#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
简单文件持久化的任务存储
支持后台长任务的状态跟踪与结果保存
"""

import json
import os
import time
import threading
from typing import Optional, Dict, Any

from ..config import TEMP_DIR

JOBS_DIR = os.path.join(TEMP_DIR, "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

_lock = threading.Lock()
_jobs_cache: Dict[str, dict] = {}


def _job_path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f"{job_id}.json")


def _save_job(job_id: str, data: dict):
    data["updated_at"] = time.time()
    with _lock:
        _jobs_cache[job_id] = data
    try:
        with open(_job_path(job_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"[JobStore] 保存任务失败 {job_id}: {e}")


def create_job(job_id: str, payload: dict) -> dict:
    data = {
        "job_id": job_id,
        "status": "pending",
        "payload": payload,
        "created_at": time.time(),
        "updated_at": time.time(),
        "progress": None,
        "result": None,
        "error": None,
    }
    _save_job(job_id, data)
    return data


def update_job(job_id: str, **kwargs) -> Optional[dict]:
    with _lock:
        data = _jobs_cache.get(job_id)
    if data is None:
        path = _job_path(job_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                return None
        else:
            return None
    data.update(kwargs)
    _save_job(job_id, data)
    return data


def get_job(job_id: str) -> Optional[dict]:
    # 优先读文件：多 worker 部署下，计算线程只更新所属 worker 的缓存，
    # 若先查缓存会导致其他 worker 永久返回过期状态
    path = _job_path(job_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _lock:
                _jobs_cache[job_id] = data
            return data
        except Exception:
            pass
    with _lock:
        return _jobs_cache.get(job_id)


def list_jobs(limit: int = 50) -> list:
    jobs = []
    try:
        for fname in sorted(os.listdir(JOBS_DIR), reverse=True):
            if fname.endswith(".json"):
                job_id = fname[:-5]
                job = get_job(job_id)
                if job:
                    jobs.append(job)
                if len(jobs) >= limit:
                    break
    except Exception:
        pass
    return jobs
