# Local KB Workbench

> 本地优先（local-first）的**个人知识库 + 工作台** · 完全离线 · 数据自持 · 零外部依赖

一个面向个人知识管理与 AI 应用作品集的本地工具。Markdown Vault 作为唯一真相源，后端零依赖（Python 标准库），前端零构建（Vue 3 本地 vendored），数据完全留在你自己的机器上。可作为日常知识管理工具，也可作为 **AI 应用面试作品集样例**。

## ✨ 特性 / Features

- 📚 **知识库**：浏览 / 编辑 Markdown，实时预览，Vault 即仓库
- 🔍 **检索**：SQLite FTS5 全文检索（命中高亮 + 摘要），可选 Chroma 语义检索（混合排序）
- 🗂️ **任务看板**：拖拽流转 待办 / 进行中 / 已完成
- 📝 **日报 / 周报**：基于文件变更与任务统计自动生成
- 🎨 **主题**：深色 / 浅色，Linear 设计美学（近黑底 + 薰衣草蓝强调色 + 发丝级边框）
- 🧩 **完全离线**：不联网、不进云，零依赖，数据自持

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

## 🚀 快速开始 / Quick Start

```bash
# 启动（无需 pip 安装任何依赖，Python 3.8+ 即可）
python backend/app.py
# 或者双击 start.bat (Windows) / 运行 ./start.sh (macOS/Linux)

# 浏览器打开
http://localhost:8080
```

首次启动会自动建立全文索引。

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
│   ├── report.py            # 日报 / 周报聚合
│   └── chroma_client.py     # 可选语义检索适配器
├── frontend/                # 零构建 Vue 前端
│   ├── index.html
│   ├── css/styles.css       # Linear 风格主题
│   ├── js/app.js            # 全部前端逻辑
│   └── vendor/              # vue.global.prod.js, marked.umd.js
├── vault/                   # 你的知识库（Markdown，随便加）
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
