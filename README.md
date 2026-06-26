# Deep Research Agent

基于百度搜索的深度研究 Agent，支持多轮搜索、信息提取、综合分析，配备会话级记忆管理系统和简洁的 Web 前端。

## 功能

- **百度搜索**：通过 HTTP 代理访问百度搜索，自动抓取搜索结果和网页内容
- **深度研究**：自动生成搜索策略 → 多轮搜索 → 信息提取 → 综合报告
- **可配置模型**：通过 IP 地址和 API Key 选择任意 OpenAI 兼容的基础模型
- **记忆管理**：按会话管理，短期记忆 + 长期摘要 + 研究资料积累
- **流式输出**：WebSocket 实时推送研究进度和生成内容
- **简洁前端**：暗色主题聊天界面，支持会话切换、Markdown 渲染

## 快速开始

```bash
cd /ssd1/gengbiao01/deepresearch
./run.sh
```

浏览器访问 `http://<服务器IP>:7860`

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DR_MODEL_BASE_URL` | `http://amu.dbh.baidu-int.com/v1` | LLM API 地址 |
| `DR_MODEL_API_KEY` | `sk-...` | LLM API Key |
| `DR_MODEL_NAME` | `deepseek-v3.1` | 模型名称 |
| `DR_SEARCH_PROXY` | `http://...:8600` | 百度搜索代理 |
| `DR_HOST` | `0.0.0.0` | 服务监听地址 |
| `DR_PORT` | `7860` | 服务端口 |

### 运行时配置

在前端界面点击「模型配置」按钮，可实时修改模型地址、API Key、模型名称等参数。

## 架构

```
deepresearch/
├── config.py              # 配置管理
├── agent/
│   ├── core.py            # 深度研究主逻辑（规划→搜索→提取→综合）
│   ├── search.py          # 百度搜索模块（代理支持）
│   ├── llm.py             # LLM 客户端（OpenAI 兼容）
│   └── memory.py          # 会话记忆管理（短期+长期+研究资料）
├── api/
│   └── server.py          # FastAPI 服务（REST + WebSocket）
├── frontend/
│   ├── index.html         # 前端页面
│   ├── style.css          # 暗色主题样式
│   └── app.js             # 前端逻辑
├── data/sessions/         # 会话数据存储（JSON）
└── run.sh                 # 启动脚本
```

### 研究流程

1. **规划**：LLM 分析问题，生成 2-4 个搜索关键词
2. **搜索**：通过代理访问百度搜索，抓取结果页面内容
3. **提取**：LLM 从每个网页提取与问题相关的关键事实
4. **综合**：LLM 综合所有资料，生成结构化研究报告（含来源引用）

### 记忆系统

- **短期记忆**：保留最近 N 条对话消息
- **长期记忆**：消息过多时自动摘要压缩，保留关键信息
- **研究资料**：跨对话积累的研究事实和来源，持续可用
