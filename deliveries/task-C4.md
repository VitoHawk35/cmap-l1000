# C4 前端换肤 Phase 0 — 交付说明

- 任务ID：C4（cmap-l1000 前端换肤 Phase 0）
- 分支：`fix/C4-reskin`
- 基线：开工时 `origin/master` @ `06a3ea2`（C1 已合并）；收工前已 rebase 到 `4c27b66`（C2 合并后），分支当前基于最新 master
- 改动文件：
  - `index.html`：全文样式与图表主题（下方列关键区间）
  - `app/main.py:19-24`（新增本地资源路径）、`app/main.py:92-101`（新增 `/bootstrap.min.css`、`/vue.min.js` 路由）
  - 新增 `bootstrap.min.css`（Bootstrap 5.3.0，232 KB）
  - 新增 `vue.min.js`（Vue 2.6.14 生产构建，94 KB）
- 未改动任何业务逻辑、API 字段与后端计算。

## 改动摘要

| 项目 | 位置 | 内容 |
|---|---|---|
| CSS 变量 | index.html:11-24 | 改成任务规定的浅色变量（`--primary:#3ecf8e` 等） |
| 深底浅字修正 | index.html:22-267 | 导航、卡片、表单、表格、gene-tag、result-info、vector-preview、alert-error、spinner 全部改为白底/浅灰底 + 深色文字 |
| 按钮 | index.html:110-136 | `.btn-primary` 绿底 + `#171717` 字 + 6px 圆角，hover `#24b47e`；补 `.btn-primary:disabled` 覆盖 Bootstrap 的蓝色禁用态；`.btn-outline` 改中性描边 |
| 分数语义 | index.html:186-187 | `.score-neg:#054cff`（负/逆转）、`.score-pos:#e2005a`（正/相似） |
| 排名徽章 | index.html:201-204 | `rank-1 #171717/白`、`rank-2 #707070/白`、`rank-3 #b2b2b2/#171717`、`rank-other #f5f5f5/#707070` |
| 等宽数字 | index.html:158,182,198,216,243,267 | `.table`、`.score-text`、`.rank`、`.count-text`、`.stats-line`、`.vector-preview` 均加 `tabular-nums` |
| ECharts 主题 | index.html:666-695 | 注册 `supabase-med`（`color:['#054cff','#e2005a','#707070']`、透明背景、`#171717` 文字、`#dfdfdf/#ededed` 轴与网格、白底 `#dfdfdf` 边框 tooltip） |
| 图表实例 | index.html:1272 | `echarts.init(el, 'supabase-med')` |
| 写死深色清除 | index.html:1292-1364 | 删除 tooltip 深底、轴标签 `#94a3b8`、dataZoom 深色、散点绿/红、白色阴影、定位点 `#fbbf24`；散点按分数正负取靛蓝/品红，趋势线改中性 `#c7c7c7` |
| resize 泄漏 | index.html:780-785、825-831、1274-1276 | `mounted` 只注册一次 `this._onResize`，`beforeDestroy` 移除并 dispose；`renderScoreChart` 重建时不再注册监听 |
| D9 离线化 | index.html:7-9、661-663；app/main.py | Bootstrap/Vue 改本地相对路径，CDN 备选保留为注释；后端仿照 echarts 增加两条静态路由 |
| 图表解读 | index.html:486-488 | 图表上方新增一句固定解读文案（颜色语义与零线含义） |
| 附带修正 | index.html:592 | 修复基线中已存在的乱码标签“细胞系���选填）”为“细胞系（选填）” |

## 测试 / 核对

1. `D:/mine_Anaconda3/python.exe -m py_compile app/main.py` → OK。
2. FastAPI `TestClient` 逐条请求：
   - `/` → 200 `text/html; charset=utf-8`（77,422 B）
   - `/bootstrap.min.css` → 200 `text/css`（232,914 B）
   - `/vue.min.js` → 200 `application/javascript`（94,151 B）
   - `/echarts.min.js` → 200 `application/javascript`（1,030,900 B）
3. 本地静态服务（`python -m http.server 8099`，指向 worktree）+ 浏览器（CDP/Playwright）手工核对：
   - 首页、药物特征解析页、结果表 Top/Bottom、图表均已截图；
   - 控制台 `console error` / `pageerror`：0 条；
   - 页面加载的所有资源均来自 `http://127.0.0.1:8099/`，`externalResources: []`（无任何 CDN 请求）；
   - 连续调用 `renderScoreChart()` 10 次后，Chrome DevTools API `getEventListeners(window).resize.length` = **1**；
   - 计算样式实测：body 背景 `rgb(255,255,255)`；主按钮 `rgb(62,207,142)` 底 + `rgb(23,23,23)` 字 + `6px` 圆角；卡片 `12px`；`.score-neg` = `rgb(5,76,255)`；`.score-pos` = `rgb(226,0,90)`；表格与分数为 `tabular-nums`；全页元素计算字重均 ≤ 500（`overWeight: []`）；
   - 图表主题实测 `color = ['#054cff','#e2005a','#707070']`。
4. 对比度（WCAG，白底）：`#707070` = 4.95、`#171717` on `#3ecf8e` = 8.98、`#054cff` = 6.03、`#e2005a` = 4.79、错误文字 `#b00047` = 7.15、`#707070` on `#f7f7f7` = 4.62、警告 `#a16207` = 4.92，全部 ≥ 4.5。

截图目录（本地，不入 git）：`D:\agent-workspace\deliveries\task-C4\`

- `01-home.png` 首页
- `02-results-top.png` 结果页（含图表 + Top 表）
- `03-chart.png` 图表特写
- `04-table-top.png` Top 表（负分靛蓝）
- `05-results-bottom.png` Bottom 视图
- `06-table-bottom.png` Bottom 表（正分品红）
- `07-extract-tab.png` 药物特征解析页

## 验收逐条核对（报告 3.7）

- [x] 页面背景纯白，无渐变（`body` 实测 `rgb(255,255,255)`，无 `linear-gradient`/`radial-gradient`）；
- [x] 每个视图最多 1 个绿色实心按钮，绿底近黑字（首页=“上传并自动解析”，结果页=“搜索”；导航激活态改为近黑底白字；主按钮 `#171717` on `#3ecf8e` = 8.98）；
- [x] 承载信息的文字不浅于 `#707070`，对比度 ≥ 4.5（逐色计算见上，最低 4.62）；
- [x] 按钮圆角 6、卡片圆角 12，无胶囊形按钮（实测 `6px` / `12px`）；
- [x] 字重不超过 500（全页扫描 `fontWeight > 500` 结果为空）；
- [x] 绿色不表达数据含义；上调/下调固定品红/靛蓝（分数、散点、WTCS 均按正负取 `#e2005a`/`#054cff`；绿色仅主按钮）；
- [x] 每张图有一句解读；CSV 导出沿用现有“导出CSV”；**SVG 导出未实现**（见“发现但未处理”）；
- [x] 所有数字等宽（表格、分数、排名、计数、向量预览均 `tabular-nums`）；
- [x] 内网断网时字体和图表可加载（无外链字体；Bootstrap/Vue/ECharts 均本地相对路径，浏览器资源记录无外部请求）。

其他验收：
- [x] 连续搜索/重绘 10 次后 `getEventListeners(window).resize.length === 1`；
- [x] 负分靛蓝、正分品红；图表散点与表格颜色一致。

## 待人工确认（🧑‍⚖️）

- **D9：CDN 离线化范围。** 本分支采用的默认建议实现：Bootstrap 5.3.0 与 Vue 2.6.14 已下载为本地文件（`bootstrap.min.css`、`vue.min.js`），`index.html` 使用同源相对路径加载；`app/main.py` 仿照 echarts 增加两条本地路由；原 CDN 写法保留为紧邻的注释行，可随时切回，未删除备选。
  - 待确认：① 是否接受把这两个文件（约 327 KB）纳入仓库；② Vue 使用生产版 `vue.min.js`（原 CDN 为开发版 `vue.js`，仅少了开发期警告，运行行为一致）；③ 是否需要同时保留 CDN-first + 本地回退的自动降级逻辑（当前为本地优先，需手工改注释回退）。
- 分支已在收工前 rebase 到含 C2 的 `4c27b66`，与 C2 的 `index.html`（`apiBaseUrl` 同源）和 `app/main.py`（CORS/startup）改动共存，后续无需再处理这两个文件的合并顺序。

## 发现但未处理

- **图表 SVG 导出**：3.7 清单要求“能导出 SVG 和 CSV”。CSV 导出已有；SVG 导出需要把图表 renderer 切到 `svg` 并新增导出入口，属于图表功能改动，Phase 0 任务原文只要求换主题与配色，故未实现，建议列入 Phase 1（ScoreDistribution 简化版一并做）。
- **瀑布线图误导性断层**：任务附录三提到的“top+bottom 拼接、横轴为序号”属报告 3.6/Phase 1 范畴，本 Phase 0 未改动图表数据组织方式（仅换主题/配色）。
- 基线 `index.html` 原有一处乱码标签已顺手修正（见改动摘要），未改其他文案。
