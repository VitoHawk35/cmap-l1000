#!/bin/bash
# CMAP 生产部署脚本

set -e

CMAP_DIR="/home/keji/cmap"
DATA_DIR="$CMAP_DIR/cmap_data"

echo "========== CMAP L1000 部署脚本 =========="

# 1. 检查数据文件
echo "[1/6] 检查数据文件..."
if [ ! -f "$DATA_DIR/fast_matrix.npy" ]; then
    echo "错误: 数据文件不存在: $DATA_DIR/fast_matrix.npy"
    echo "请先上传数据文件！"
    exit 1
fi

# 2. 创建目录
echo "[2/6] 创建目录..."
mkdir -p /var/log/cmap
mkdir -p $CMAP_DIR

# 3. 安装依赖
echo "[3/6] 安装Python依赖..."
cd $CMAP_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-prod.txt

# 4. 复制代码
echo "[4/6] 复制应用代码..."
# 假设代码已通过git clone或scp上传
# git clone https://github.com/your-repo/cmap.git .

# 5. 配置systemd
echo "[5/6] 配置systemd服务..."
cp deploy/cmap.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable cmap

# 6. 启动服务
echo "[6/6] 启动服务..."
systemctl start cmap

echo "========== 部署完成 =========="
echo "API地址: http://10.71.219.177:8001"
echo "查看状态: systemctl status cmap"
echo "查看日志: journalctl -u cmap -f"