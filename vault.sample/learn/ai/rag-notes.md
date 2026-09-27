---
title: RAG 检索增强生成 · 学习笔记
tags: [AI, RAG, 示例]
---

# RAG（Retrieval-Augmented Generation）速记

## 核心流程

1. **切分**：把文档切成合适粒度的 chunk
2. **向量化**：用 embedding 模型把 chunk 编码为向量
3. **检索**：用户提问 → 编码 → 向量检索 top-k 相关 chunk
4. **生成**：把检索到的上下文拼进 prompt，交给 LLM 生成答案

## 常见优化

- **混合检索**：向量（语义）+ BM25 / FTS（关键词）互补
- **重排（Rerank）**：先粗召回，再用 cross-encoder 精排
- **MMR**：在相关性和多样性之间做平衡，避免结果同质

## 本项目怎么做的

- 默认 **SQLite FTS5** 全文检索（零依赖、开箱即用）
- 可选 **Chroma** 向量检索，缺失时自动降级为纯全文
- 中文场景下 FTS5 `unicode61` tokenizer 不分词，额外加了**子串 fallback**
