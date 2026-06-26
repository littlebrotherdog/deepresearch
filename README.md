# Deep Research Agent

基于多引擎搜索的深度研究 Agent，支持百度、Google、Google Scholar、arXiv，自动完成多轮搜索、信息提取、综合分析，配备会话级记忆管理系统和简洁的 Web 前端。

## 功能

- **多引擎搜索**：百度、Google、Google Scholar、arXiv 四大搜索引擎全覆盖
- **深度研究**：自动生成搜索策略 → 多轮搜索 → 信息提取 → 综合报告
- **可配置模型**：通过 API 地址和 API Key 选择任意 OpenAI 兼容的基础模型
- **记忆管理**：按会话管理，短期记忆 + 长期摘要 + 研究资料积累
- **流式输出**：WebSocket 实时推送研究进度和生成内容
- **导出功能**：支持将研究结果导出为 Markdown 或 PDF
- **简洁前端**：暗色主题聊天界面，支持会话切换、Markdown 渲染

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
./run.sh
```

浏览器访问 `http://localhost:7860`

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DR_MODEL_BASE_URL` | - | LLM API 地址 |
| `DR_MODEL_API_KEY` | - | LLM API Key |
| `DR_MODEL_NAME` | `deepseek-v3.1` | 模型名称 |
| `DR_SEARCH_PROXY` | - | 搜索代理地址 |
| `DR_SEARCH_ENGINES` | `baidu,google,scholar,arxiv` | 启用的搜索引擎（逗号分隔） |
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
│   ├── search.py          # 多引擎搜索模块（百度/Google/Scholar/arXiv）
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
2. **搜索**：多引擎并行搜索（百度/Google/Scholar/arXiv），抓取结果页面内容
3. **提取**：LLM 从每个网页提取与问题相关的关键事实
4. **综合**：LLM 综合所有资料，生成结构化研究报告（含来源引用）

### 搜索引擎

| 引擎 | 类型 | 说明 |
|------|------|------|
| `baidu` | 网页搜索 | 百度搜索，中文内容覆盖好 |
| `google` | 网页搜索 | Google 搜索，英文和全球信息覆盖广 |
| `scholar` | 学术搜索 | Google Scholar，学术论文和引用信息 |
| `arxiv` | 学术搜索 | arXiv API，预印本论文，无需页面抓取 |

通过环境变量 `DR_SEARCH_ENGINES` 可自由组合，例如只启用学术搜索：`DR_SEARCH_ENGINES=scholar,arxiv`

### 记忆系统

- **短期记忆**：保留最近 N 条对话消息
- **长期记忆**：消息过多时自动摘要压缩，保留关键信息
- **研究资料**：跨对话积累的研究事实和来源，持续可用
