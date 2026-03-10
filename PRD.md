# 项目背景
本地化复现 CMAP L1000 数据库，用于 AI 制药靶点检索。

# 数据说明（文件存放于 D:\mine_python_project\CMAP\cmap_data）
1. `fast_matrix.npy`: 形状为 (12328, 473647) 的 float32 矩阵。由于高达 23GB，必须使用 `numpy.memmap` 读取，绝不能 load 进内存！
2. `col_sig_ids.csv`: 长度为 473647 的实验列名列表。
3. `row_gene_ids.csv`: 长度为 12328 的基因行名列表。
4. `GSE92742_Broad_LINCS_sig_info.txt`: 元数据字典（包含 pert_iname, cell_id, pert_idose 等字段）。

# 核心业务接口需求
【接口1：特征提取】输入药物名(drug)、细胞系(cell_line)、浓度(dose)，去 `sig_info.txt` 模糊查询拿到对应的 `sig_id`。利用 `memmap` 从 `fast_matrix.npy` 极速切片提取对应的列，返回 12000 维向量。
【接口2：疾病特征逆转匹配（全库搜药）】输入 up_genes 和 down_genes 两个 Entrez ID 列表。构建 1x12328 的查询向量（上调位置标1，下调位置标-1，其余0）。使用 Cosine 策略计算该查询向量与全库 473647 次实验的余弦相似度。返回得分最负（最能逆转疾病）的 Top-50 药物并关联其 metadata。