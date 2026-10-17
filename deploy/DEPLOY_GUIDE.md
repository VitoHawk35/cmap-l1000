# CMAP L1000 完整部署方案

## 服务器信息

- **内网IP**: `10.71.219.177`
- **数据目录**: `/home/keji/cmap`
- **API端口**: `8001` (8000/8080已被占用)
- **前端端口**: `80` (Nginx)

---

## 部署前准备

### 1. 本地准备（压缩并上传代码）

在本地执行：

```bash
# 进入项目目录
cd d:/mine_python_project/CMAP

# 压缩代码（排除数据文件和临时文件）
tar czvf cmap_deploy.tar.gz \
  --exclude='cmap_data' \
  --exclude='temp' \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='heada5' \
  --exclude='*.pdf' \
  --exclude='*.xlsx' \
  --exclude='*.csv' \
  app/ deploy/ index.html requirements-prod.txt run.py

# 上传到服务器
scp cmap_deploy.tar.gz keji@10.71.219.177:/home/keji/

# 上传数据文件（单独上传，因为很大）
rsync -avz --progress cmap_data/fast_matrix.npy keji@10.71.219.177:/home/keji/cmap/cmap_data/
rsync -avz --progress cmap_data/*.csv cmap_data/*.txt.gz keji@10.71.219.177:/home/keji/cmap/cmap_data/
```

### 2. 服务器准备（解压代码）

在服务器上执行：

```bash
ssh keji@10.71.219.177

# 创建目录
mkdir -p /home/keji/cmap

# 解压代码
cd /home/keji
tar xzvf cmap_deploy.tar.gz -C cmap/

# 检查结构
ls -la /home/keji/cmap/
```

---

## 方案一：Docker部署（推荐）

### 前提条件

```bash
# 检查Docker是否安装
docker --version
docker-compose --version

# 如果没有安装
sudo apt update
sudo apt install docker.io docker-compose
sudo usermod -aG docker keji
newgrp docker
```

### 部署步骤

```bash
cd /home/keji/cmap/deploy

# 1. 构建并启动服务
docker-compose up -d --build

# 2. 检查状态
docker-compose ps

# 3. 查看日志
docker-compose logs -f cmap-api

# 4. 健康检查
curl http://10.71.219.177:8001/health
```

### 常用命令

```bash
# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看实时日志
docker-compose logs -f --tail=100

# 更新代码后重新构建
docker-compose up -d --build
```

---

## 方案二：Systemd部署（传统方式）

### 前提条件

```bash
# 安装Python和依赖
sudo apt update
sudo apt install -y python3.9 python3.9-venv python3-pip nginx curl

# 创建日志目录
sudo mkdir -p /var/log/cmap
sudo chown -R keji:keji /var/log/cmap
```

### 部署步骤

```bash
cd /home/keji/cmap

# 1. 创建虚拟环境
python3.9 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install --upgrade pip
pip install -r requirements-prod.txt

# 3. 测试启动（前台运行，测试是否正常）
gunicorn -w 1 --threads 8 \
  -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8001 \
  --timeout 300 \
  --keep-alive 60 \
  app.main:app

# 按 Ctrl+C 停止测试

# 4. 配置Systemd服务
sudo cp deploy/cmap.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. 启动服务
sudo systemctl enable cmap
sudo systemctl start cmap

# 6. 检查状态
sudo systemctl status cmap
sudo journalctl -u cmap -f
```

### 配置Nginx（可选，用于80端口访问）

```bash
# 1. 复制配置
sudo cp deploy/nginx.conf /etc/nginx/nginx.conf

# 2. 测试配置
sudo nginx -t

# 3. 重启Nginx
sudo systemctl restart nginx

# 4. 检查Nginx状态
sudo systemctl status nginx
```

### 常用命令

```bash
# 查看服务状态
sudo systemctl status cmap

# 查看日志
sudo journalctl -u cmap -f --since "1 hour ago"

# 重启服务
sudo systemctl restart cmap

# 停止服务
sudo systemctl stop cmap

# 查看Nginx日志
sudo tail -f /var/log/nginx/access.log
```

---

## 验证部署

### 1. API健康检查

```bash
# 健康检查
curl http://10.71.219.177:8001/health

# 预期输出: {"status":"healthy"}
```

### 2. API文档

浏览器访问: http://10.71.219.177:8001/docs

### 3. 测试搜索接口

```bash
# 测试Cosine搜索
curl -X POST http://10.71.219.177:8001/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"up_genes":[1,2,3],"down_genes":[100,101],"top_k":10}'

# 测试WTCS搜索
curl -X POST http://10.71.219.177:8001/api/v1/search_wtcs \
  -H "Content-Type: application/json" \
  -d '{"up_genes":[1,2,3],"down_genes":[100,101],"top_k":10}'
```

### 4. 前端访问

如果使用Nginx: http://10.71.219.177

如果直接访问API: 需要修改 index.html 中的 apiBaseUrl 为当前服务器IP

---

## 常见问题

### 1. 端口被占用

```bash
# 检查端口占用
netstat -tlnp | grep 8001

# 如果被占用，修改 deploy/docker-compose.yml 或 deploy/cmap.service 中的端口
```

### 2. 内存不足

```bash
# 查看内存使用
free -h

# 创建交换分区
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 添加到 /etc/fstab 永久生效
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 3. 权限问题

```bash
# 修复权限（Systemd方案）
sudo chown -R keji:keji /home/keji/cmap
sudo chmod -R 755 /home/keji/cmap

# 如果使用www-data用户运行
sudo chown -R www-data:www-data /home/keji/cmap
```

### 4. 数据文件找不到

```bash
# 检查数据文件是否存在
ls -lh /home/keji/cmap/cmap_data/fast_matrix.npy

# 检查权限
ls -la /home/keji/cmap/cmap_data/
```

### 5. Docker无法访问数据

```bash
# 检查数据目录权限
ls -la /home/keji/cmap/cmap_data/

# 确保目录有读取权限
chmod -R 755 /home/keji/cmap/cmap_data/
```

---

## 性能优化

### 1. 调整工作进程数

**固定 `-w 1 --threads 8`，不要按 CPU 核心数开多 worker**（memmap 不共享；Tau 后台任务运行在 worker 线程中，多 worker 回收会丢任务、状态停留在 running）：

```bash
# 修改 deploy/cmap.service、deploy/Dockerfile 或 start.sh 中的 gunicorn 参数
-w 1 --threads 8
```

### 2. 内存限制

```bash
# 查看内存使用
docker stats  # Docker方案

# 或
ps aux | grep gunicorn  # Systemd方案
```

### 3. 日志轮转

```bash
# 安装logrotate
sudo apt install logrotate

# 创建配置文件
sudo tee /etc/logrotate.d/cmap << 'EOF'
/var/log/cmap/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 keji keji
}
EOF
```

---

## 备份与恢复

### 备份数据

```bash
# 备份数据文件
tar czvf cmap_data_backup_$(date +%Y%m%d).tar.gz /home/keji/cmap/cmap_data/

# 备份代码
tar czvf cmap_code_backup_$(date +%Y%m%d).tar.gz /home/keji/cmap/app/ /home/keji/cmap/deploy/
```

### 恢复数据

```bash
# 恢复数据文件
tar xzvf cmap_data_backup_20240101.tar.gz -C /

# 重启服务
docker-compose restart  # 或 sudo systemctl restart cmap
```

---

## 更新代码

```bash
cd /home/keji/cmap

# 1. 备份当前代码
cp -r app app_backup_$(date +%Y%m%d)

# 2. 上传新代码（本地执行）
rsync -avz --exclude 'cmap_data' --exclude '.git' app/ deploy/ keji@10.71.219.177:/home/keji/cmap/

# 3. 重启服务（服务器上执行）
# Docker方案:
cd /home/keji/cmap/deploy
docker-compose up -d --build

# Systemd方案:
sudo systemctl restart cmap
```

---

## 安全建议

1. **防火墙配置**:
   ```bash
   # 只开放必要端口
   sudo ufw allow 80/tcp
   sudo ufw allow 8001/tcp
   sudo ufw enable
   ```

2. **限制IP访问**（如需）:
   ```bash
   # 修改 deploy/nginx.conf
   # 在 server 块中添加:
   allow 10.71.0.0/16;
   deny all;
   ```

3. **定期更新**:
   ```bash
   # 更新系统
   sudo apt update && sudo apt upgrade -y

   # 更新Docker镜像
   docker-compose pull
   docker-compose up -d
   ```

---

## 联系支持

如遇到问题，请检查：
1. 服务日志: `docker-compose logs` 或 `journalctl -u cmap`
2. 数据文件权限: `ls -la /home/keji/cmap/cmap_data/`
3. API健康: `curl http://10.71.219.177:8001/health`