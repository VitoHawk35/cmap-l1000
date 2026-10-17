# CMAP L1000 生产部署指南

## 服务器配置信息

- **内网IP**: `10.71.219.177`
- **端口占用**: 8000、8080 已被占用
- **已修改为**: API使用 **8001** 端口，Nginx使用 **80** 端口

---

## 方案选择

| 方案 | 适用场景 | 复杂度 |
|------|----------|--------|
| **Docker部署** | 推荐，易于管理 | 低 |
| **Systemd部署** | 传统服务器 | 中 |
| **手动部署** | 调试开发 | 高 |

---

## 方案一：Docker部署（推荐）

### 1. 准备数据（在服务器上）

```bash
mkdir -p /home/keji/cmap
cd /home/keji/cmap

# 上传数据文件（本地执行）
rsync -avz --progress cmap_data/ user@10.71.219.177:/home/keji/cmap/cmap_data/

# 上传代码（本地执行）
rsync -avz --exclude 'temp' --exclude '.git' . user@10.71.219.177:/home/keji/cmap/
```

### 2. 启动服务（服务器上）

```bash
cd /home/keji/cmap/deploy

# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f cmap-api

# 停止
docker-compose down
```

---

## 方案二：Systemd部署

### 1. 准备环境

```bash
# 安装Python3.9
sudo apt update
sudo apt install python3.9 python3.9-venv python3-pip nginx

# 创建目录
sudo mkdir -p /home/keji/cmap /var/log/cmap

# 上传代码和数据到 /home/keji/cmap
```

### 2. 安装依赖

```bash
cd /home/keji/cmap
python3.9 -m venv venv
source venv/bin/activate
pip install -r requirements-prod.txt
```

### 3. 配置服务

```bash
# 复制服务配置
sudo cp deploy/cmap.service /etc/systemd/system/
sudo systemctl daemon-reload

# 启动服务
sudo systemctl enable cmap
sudo systemctl start cmap

# 检查状态
sudo systemctl status cmap
sudo journalctl -u cmap -f
```

### 4. 配置Nginx（可选，用于80端口）

```bash
sudo cp deploy/nginx.conf /etc/nginx/nginx.conf
sudo systemctl restart nginx
```

---

## 关键配置说明

### 工作进程数

固定单 worker + 多线程（memmap 不共享；Tau 后台任务运行在 worker 线程中，多 worker 会被回收丢任务）：

```bash
# Dockerfile或systemd中
-w 1 --threads 8
```

### 内存需求

- **最低**: 4GB RAM（单进程）
- **推荐**: 8GB RAM（单进程 + 8 线程）
- **磁盘**: 30GB（数据23GB + 系统）

### 超时设置

- **Cosine/WTCS搜索**: 30-60秒
- **Tau搜索**: 10-15分钟
- 配置在 `nginx.conf` 和 `gunicorn` 参数中

---

## 验证部署

```bash
# 健康检查
curl http://localhost:8000/health

# API文档
curl http://localhost:8000/docs

# 测试搜索
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"up_genes":[1,2,3],"down_genes":[100,101],"top_k":10}'
```

---

## 常见问题

### 1. 数据文件加载失败

检查路径是否正确：
```python
# 在服务器上测试
python -c "from app.core.matrix_store import MatrixStore; m = MatrixStore(); print(m.shape)"
```

### 2. 内存不足

- 减少工作进程数：`-w 2`
- 增加交换分区：
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 3. 权限问题

```bash
sudo chown -R www-data:www-data /home/keji/cmap
sudo chmod -R 755 /home/keji/cmap
```

---

## 监控与维护

### 查看日志

```bash
# Docker
docker-compose logs -f --tail=100

# Systemd
sudo journalctl -u cmap -f --since "1 hour ago"
```

### 重启服务

```bash
# Docker
docker-compose restart cmap-api

# Systemd
sudo systemctl restart cmap
```

### 备份数据

```bash
tar czvf backup_$(date +%Y%m%d).tar.gz /home/keji/cmap/cmap_data/
```