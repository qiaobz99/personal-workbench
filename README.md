# Local KB Workbench

> 本地优先（local-first）的**个人知识库 + 工作台** · 完全离线 · 数据自持 · 零外部依赖

一个面向个人知识管理与 AI 应用作品集的本地工具。Markdown Vault 作为唯一真相源，后端零依赖（Python 标准库），前端零构建（Vue 3 本地 vendored），数据完全留在你自己的机器上。可作为日常知识管理工具，也可作为 **AI 应用面试作品集样例**。

## ✨ 特性 / Features

- 📚 **知识库**：浏览 / 编辑 Markdown，实时预览，Vault 即仓库
- 🔍 **检索**：SQLite FTS5 全文检索（命中高亮 + 摘要），可选 Chroma 语义检索（混合排序）
- 🗂️ **任务看板**：拖拽流转 待办 / 进行中 / 已完成
- 🧭 **日常工作**：需求 → 设计 → 开发 → Bug 一条链；状态流转自动写入文件内时间线；约定卡片墙；历史文档（含 .docx）批量导入
- 📝 **日报 / 周报**：基于文件变更与任务统计自动生成
- 🎨 **主题**：深色 / 浅色，Linear 设计美学（近黑底 + 薰衣草蓝强调色 + 发丝级边框）
- 🧩 **完全离线**：不联网、不进云，零依赖，数据自持

## 🔒 隐私 / Privacy

你的笔记只存在于本机 `vault/` 目录，**不会被提交到 Git**（`.gitignore` 已排除）。
仓库里只有代码和 `vault.sample/` 示例内容 —— 公开分享代码时，不会泄露任何个人数据。

## 🏗️ 架构 / Architecture

```
┌───────────────────────────────────────────────┐
│  表现层   Vue 3 (零构建) + marked.js            │
├───────────────────────────────────────────────┤
│  服务层   Python 标准库 http.server (零依赖)     │
├───────────────────────────────────────────────┤
│  索引层   SQLite FTS5 (全文) + Chroma (语义)    │
├───────────────────────────────────────────────┤
│  存储层   Vault (Markdown 目录) — 唯一真相源    │
└───────────────────────────────────────────────┘
```

**索引链路参考**：语义 + 词汇混合检索 + MMR 重排（借鉴 Second Brain 的设计），Chroma 缺失时自动降级为纯 FTS5 全文。

## 🧭 日常工作 / Work Zone

**一套文件，两种视图**：知识库按目录树看这些文件，日常工作按「工作项」看同一批文件。给 Markdown 加一层很轻的 frontmatter 就够了，不新造一份数据。

```
vault/work/
├── _conventions/                  # 工作约定与纪律（卡片墙）
├── _inbox/                        # 导入后的待整理区
└── <project>/                     # 一个项目 / 业务线一个目录
    ├── req/REQ-001-xxx.md         # 需求
    ├── design/DES-001-xxx.md      # 设计
    ├── dev/DEV-001-xxx.md         # 开发
    └── bug/BUG-001-xxx.md         # Bug（正文只留「原因」「方案」）
```

侧边栏「日常工作」下六个子菜单：**总览 / 需求 / 设计 / 开发 / Bug / 约定**，每个子菜单就是按 `type` 过滤同一批文件。

- **进度留在文件里**：状态变动自动往正文的 `## 进展` 追加一行带时间戳的记录，数据库丢了进度还在，换台机器拷走 `vault/` 也还在。
- **需求 → 设计 → 开发 → Bug 是一条链**：用 `refs` / `project` 串起来，不是四份孤立数据。
- **历史导入**：填一个本地目录即可递归扫描 `.md / .txt / .docx`（docx 用标准库 `zipfile` + `xml.etree` 直接解析，不需要 python-docx），原文完整保留在正文，同名不覆盖。

API 一览（与现有 `/api/*` 同一套 `_api` 分发）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/work/board` | 日常工作聚合（进行中 / 卡点 / 本周进展） |
| GET | `/api/work/items?type=&project=&status=&q=` | 工作项列表 |
| GET | `/api/work/item?path=` | 单个工作项（字段 + 正文 + 时间线） |
| POST | `/api/work/item` | 新建（自动编号 + 模板 + 骨架） |
| PUT | `/api/work/item` | 更新字段 / 正文（**状态变更自动追加时间线**） |
| DELETE | `/api/work/item?path=` | 删除 |
| POST | `/api/work/import/scan` | 扫描本地目录（只读，出候选列表） |
| POST | `/api/work/import` | 批量导入 |
| GET | `/api/work/meta` | 类型 / 状态机 / 枚举（供前端渲染） |

## 🚀 快速开始 / Quick Start

```bash
# 启动（无需 pip 安装任何依赖，Python 3.8+ 即可）
python backend/app.py
# 或者双击 start.bat (Windows) / 运行 ./start.sh (macOS/Linux)

# 浏览器打开
http://localhost:17321
```

> 端口默认 **17321**（刻意避开 3000 / 5000 / 8000 / 8080 / 8888 这些被各种开发工具抢占的端口）。
> 要换端口：设环境变量 `KB_PORT` 即可，如 `KB_PORT=9001 python backend/app.py`。

首次启动会自动建立全文索引。仓库自带 `vault.sample/` 示例内容，可先复制成你的 `vault/`：

```bash
cp -r vault.sample vault        # macOS / Linux
xcopy vault.sample vault /E /I  # Windows
```

## 🧠 启用语义检索（可选）/ Semantic Search (optional)

默认仅 FTS5 全文。若要语义（向量）检索：

```bash
pip install chromadb sentence-transformers
# 重启服务，设置页会显示「语义检索已启用 (Chroma)」
```

未安装时自动降级为纯全文检索，功能不受影响。

## 📁 目录结构 / Layout

```
local-kb-workbench/
├── backend/                 # Python 标准库后端（零依赖）
│   ├── app.py               # HTTP 服务 + JSON API
│   ├── config.py            # 配置
│   ├── store.py             # SQLite FTS5 索引 + 任务看板
│   ├── vault.py             # Vault 读写
│   ├── indexer.py           # 增量 / 全量索引
│   ├── work.py              # 日常工作：frontmatter 解析 / 工作项 / 时间线 / 导入
│   ├── report.py            # 日报 / 周报聚合
│   └── chroma_client.py     # 可选语义检索适配器
├── frontend/                # 零构建 Vue 前端
│   ├── index.html
│   ├── css/styles.css       # Linear 风格主题
│   ├── js/app.js            # 全部前端逻辑
│   └── vendor/              # vue.global.prod.js, marked.umd.js
├── vault/                   # 你的私人知识库（Markdown）— 已 gitignore，永不提交
├── vault.sample/            # 示例知识库（首次可复制为 vault/）
├── data/                    # 运行时生成（db / log），已 gitignore
├── start.bat / start.sh     # 一键启动
└── README.md
```

## 🛠️ 技术栈 / Tech Stack

Python 3.8+ · SQLite FTS5 · Chroma (optional) · Vue 3 · marked · 零构建

## 📌 设计取舍 / Design Notes

- **零依赖优先**：后端仅用标准库，前端用 global build，开箱即跑，无 `npm install` / `pip install` 负担。
- **本地优先**：Vault 是纯 Markdown，可被任意编辑器 / Git / 其他工具直接消费，不被锁定。
- **渐进增强**：语义检索是可选项，缺失自动降级，绝不阻塞核心功能。

## 🤝 适用场景 / Use Cases

- 个人知识沉淀（工作笔记、学习、面试准备）
- 本地离线工作台（检索 / 看板 / 周报）
- AI 应用方向的项目作品集（面试可讲解：local-first 架构、FTS5 + 向量混合检索、零依赖设计）

---

*Local-first knowledge base & workbench. Fully offline, data stays on your machine.*
