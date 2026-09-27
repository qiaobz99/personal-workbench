# Vault（示例）

这是**示例知识库**，用于演示目录结构。

> ⚠️ 真正的 `vault/` 是你的**私人**知识库，已被 `.gitignore` 排除，**永远不会被提交到 Git**。
> 本目录只是让项目克隆下来能立刻看到内容、跑起来。

## 用法

首次运行前，把示例复制成你自己的 vault：

```bash
# macOS / Linux
cp -r vault.sample vault

# Windows (cmd)
xcopy vault.sample vault /E /I
```

然后把 `vault/` 里的内容换成你自己的 Markdown 笔记即可（目录、文件可任意增删）。

## 目录约定（仅示例，可自定义）

| 目录 | 用途 |
| --- | --- |
| `daily/` | 每日笔记 |
| `learn/` | 学习笔记（如 AI / RAG） |
| `work/` | 工作项目 |
| `life/` | 生活记录 |

> 你也可以用环境变量 `KB_VAULT` 指向任意目录作为知识库根，不必叫 `vault`。
