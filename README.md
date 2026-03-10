# CMAP L1000 药物筛选平台

基于 LINCS L1000 基因表达数据的药物特征提取与疾病逆转匹配系统。

## 项目简介

本项目提供两个核心功能：

1. **药物特征提取** - 根据药物名称、细胞系、剂量查询其诱导的基因表达特征向量（12328维）
2. **疾病逆转搜索** - 根据疾病的上调/下调基因特征，在全库473647次实验中搜索最能逆转该疾病的药物

## 技术栈

- **后端**: FastAPI + Python 3.8+
- **数据存储**: NumPy memmap (23GB矩阵零拷贝访问)
- **前端**: Vue 2 + Bootstrap 5 (单文件HTML)
- **数据处理**: Pandas, HDF5

## 项目结构

```
CMAP/
├── 01_build_memmap.py       # 数据预处理脚本（一次性运行）
├── index.html               # 前端页面（直接浏览器打开）
├── run.py                   # 服务启动脚本
├── requirements.txt         # Python依赖
├── app/                     # 后端应用代码
│   ├── main.py             # FastAPI入口
│   ├── config.py           # 配置管理
│   ├── core/               # 数据访问层
│   │   ├── matrix_store.py    # Memmap矩阵访问
│   │   └── metadata_index.py  # 元数据索引
│   ├── scoring/            # 打分策略
│   │   ├── base_scorer.py
│   │   └── cosine_scorer.py
│   └── api/                # API接口
│       ├── extract.py
│       └── search.py
└── cmap_data/              # 数据目录（Git忽略）
    ├── fast_matrix.npy     # 23GB特征矩阵（预处理生成）
    ├── col_sig_ids.csv     # 列名映射
    └── row_gene_ids.csv    # 行名映射
```

## 快速开始

### 1. 环境准备

```bash
# 创建conda环境
conda create -n cmap python=3.8
conda activate cmap

# 安装依赖
pip install -r requirements.txt
```

### 2. 数据准备

下载 CMAP L1000 Level 5 数据并预处理：

```bash
# 运行预处理脚本（生成23GB memmap文件，只需执行一次）
python 01_build_memmap.py
```

需要的源数据文件（放置于 `cmap_data/` 目录）：
- `GSE92742_Broad_LINCS_Level5_COMPZ.MODZ_n473647x12328.gctx.gz`
- `GSE92742_Broad_LINCS_sig_info.txt.gz`
- `GSE92742_Broad_LINCS_gene_info.txt.gz`

### 3. 启动服务

```bash
python run.py
```

服务将运行在 `http://localhost:8000`

### 4. 使用前端

直接用浏览器打开 `index.html` 文件即可使用。

## API文档

启动服务后访问：`http://localhost:8000/docs`

### 接口1：特征提取

```bash
POST /api/v1/extract
{
    "drug": "aspirin",
    "cell_line": "A375",    // 可选
    "dose": "10 µM"         // 可选
}
```

### 接口2：疾病逆转搜索

```bash
POST /api/v1/search
{
    "up_genes": [1, 2, 3, 4, 5],
    "down_genes": [100, 101, 102],
    "top_k": 50
}
```

## 内存优化说明

- 使用 `numpy.memmap` 实现23GB矩阵的零拷贝访问
- 流式处理避免内存溢出（单次查询内存占用 < 500MB）
- 全库扫描采用分块批量计算 + 堆优化Top-K

## 许可证

MIT License
