# D3 旧页面与杂项（cmap 部分）— 交付说明

- 任务ID：D3（R13：色板外颜色改冷色；FDR<0.05 字重 700→500）
- 分支：`fix/D3-cleanup`
- 基线：`origin/master` @ `40dfe9c`
- 改动文件：仅 `index.html`（25 行替换，无增删行）
- 未改动任何业务逻辑、API 字段与后端计算；未改 §4.2 设计令牌值。

## 改动摘要

| 项目 | 位置 | 改动前 → 改动后 |
|---|---|---|
| 琥珀色警示变量 | :root（原 20 行） | 删除色板外 `--warning: #a16207`（全文件仅 1 处使用） |
| 无效基因警示框 | index.html 原 362-363 行 | 底 `rgba(245,158,11,0.05)` → 令牌 `--warn-bg #ffdb13`；字 `var(--warning)` → 近黑 `#171717`（黄底近黑字，符合令牌语义） |
| 近白灰归一 | 多处 | `#f7f7f7` → `#fafafa`（--canvas-soft，表头/卡片头）；`#f5f5f5` → `#ededed`（--hairline-cool，悬停/标签/进度条底色） |
| 品红字色修正 | alert-error、gene-tag ×3 | `#b00047` → 令牌 `#b0004a`（--gene-up-fg） |
| 缩写白色 | rank-1/rank-2 | `#fff` → `#ffffff`（值不变，统一写法） |
| FDR 字重（任务核心） | index.html 原 562 行 | `fontWeight: fdr<0.05 ? '700':'400'` → `'500':'400'`；强调改为"近黑色 + 500 字重"：`fdr<0.05` 时 `color:'#171717'`（fdr>0.25 置灰逻辑不变，优先级保持） |
| 紫色序列改冷色 | SEQ_COLORS（原 678 行） | `['#f5f0fb','#eddbf9','#b9a6e8','#644fc1','#3b2a85']` → 靛蓝序列 `['#e6edff','rgba(5,76,255,0.3)','rgba(5,76,255,0.55)','#054cff','#0438c4']`（浅→深语义不变） |
| 散点中间色改冷色 | DIV_COLORS（原 676 行） | `['#054cff','#7da0fa','#f5f5f5','#eb7aa7','#e2005a']` → `['#054cff','rgba(5,76,255,0.45)','#ededed','rgba(226,0,90,0.35)','#e2005a']`（端点色不变，中间档用令牌色的透明度变体） |
| tooltip 阴影 | supabaseMedTheme（原 691 行） | `rgba(0,0,0,.08)` → `rgba(23,23,23,.08)`（纯黑不在白名单，改近黑同透明度） |

说明：透明度变体（如 `rgba(5,76,255,0.45)`）按任务包 V-F2"颜色允许透明度变化"的约定视为白名单内；所有 rgba 基色均为令牌色（#054cff / #e2005a / #3ecf8e / #171717）。

## 自测验收

1. **字重** ✅：`grep -nE "fontWeight:\s*'?(700|600|bold)'?|font-weight:\s*(700|600|bold)|\b700\b" index.html` → 无输出；现存 `fontWeight` 仅 `500`。
2. **颜色白名单** ✅：提取全部 hex 与 rgba 基色，逐一比对 §4.2 令牌（含 `#fff` 等价项）→ 无白名单外颜色。审计输出见 `D:\agent-workspace\deliveries\task-D3\cmap-color-audit.txt`。
3. **测试不回归** ✅：`D:\agent-workspace\venvs\cmap-c0-38\Scripts\python.exe -m pytest -q` → **39 passed, 1 skipped**（与基线一致）。

## 主agent验收命令

```bash
# cmap-l1000 仓库 fix/D3-cleanup 分支
grep -nE "fontWeight: *'?700'?|font-weight: *700|\\b700\\b" index.html        # 期望无输出
grep -noE '#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}\b' index.html | awk -F: '{print $2}' | sort -u \
  | grep -viE '^#(3ecf8e|24b47e|11845b|707070|9a9a9a|b2b2b2|171717|212121|ffffff|fafafa|1c1c1c|dfdfdf|c7c7c7|ededed|e2005a|054cff|fde6ef|b0004a|e6edff|0438c4|ffdb13|fff)$'
# ↑ 期望无输出（rgba 基色另需人工过目，本分支全部为 5,76,255 / 226,0,90 / 62,207,142 / 23,23,23）
D:\agent-workspace\venvs\cmap-c0-38\Scripts\python.exe -m pytest -q            # 期望 39 passed, 1 skipped
```

## 待人工确认项

- 无。

## 发现但未处理项

- `SEQ_COLORS` 在当前 index.html 中定义后未被引用（现状即如此，未删——只加不删，供后续图表使用，已同步改为令牌内冷色）。
- §4.6 火山图规范中的"其余 #d4d4d4"本身不在 §4.2 令牌白名单内；本文件未使用该值，无需处理，提请主agent在 F 系任务统一裁定。
