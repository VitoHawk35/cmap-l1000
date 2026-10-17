#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""健康检查与前端托管冒烟测试"""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_index_served(client):
    """前端 index.html 同源托管"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "html" in resp.headers["content-type"].lower()
