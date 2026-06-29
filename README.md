# Deep Research Agent

基于多引擎搜索的深度研究 Agent，支持百度、Google、Google Scholar、arXiv，自动完成多轮搜索、信息提取、综合分析，配备会话级记忆管理系统、内置基准评测面板和简洁的 Web 前端。

## 功能

- **多引擎搜索**：百度、Google、Google Scholar、arXiv 四大搜索引擎全覆盖
- **深度研究**：自动生成搜索策略 → 多轮搜索 → 信息提取 → 综合报告
- **可配置模型**：通过 API 地址和 API Key 选择任意 OpenAI 兼容的基础模型
- **记忆管理**：按会话管理，短期记忆 + 长期摘要 + 研究资料积累
- **流式输出**：WebSocket 实时推送研究进度和生成内容
- **导出功能**：支持将研究结果导出为 Markdown 或 PDF（PDF 渲染库已本地化，无需外网）
- **基准评测**：内置 C-Eval / CMMLU / MMLU / CMATH 评测，多模型并行跑分，按学科拆解准确率
- **简洁前端**：暗色主题聊天界面，支持会话切换、Markdown 渲染（单体 `index.html`）

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
./run.sh
```

浏览器访问 `http://localhost:7860`。

### （可选）准备评测数据集

评测功能需要先下载一次数据集。[scripts/download_datasets.py](scripts/download_datasets.py) 默认经 **hf-mirror.com** 镜像拉取，无需翻墙；如需切回官方端点可自行设置环境变量 `HF_ENDPOINT=https://huggingface.co`。

```bash
./run.sh prepare ceval      # 仅 C-Eval（最小）
# 或全部四个：
./run.sh prepare all        # ceval, cmmlu, mmlu, cmath
```

也可直接调用脚本：`python scripts/download_datasets.py [ceval|cmmlu|mmlu|cmath|all]`
（需先安装 `datasets` 库）。未下载数据集时，主流程的深度研究与对话不受影响。

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

在前端界面点击「模型配置」按钮，可实时修改模型地址、API Key、模型名称等参数；
在「评测」入口可选择已下载的数据集与多个候选模型并发跑分对比。

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
│   └── server.py          # FastAPI 服务（REST + WebSocket ×2：chat/eval）
├── eval/
│   ├── datasets.py        # 数据集加载与归一化（C-Eval/CMMLU/MMLU/CMATH）
│   ├── models.py          # 评测数据模型（题目/答案/run 记录）
│   ├── prompts.py         # 提示模板 + 答案抽取与判分
│   └── runner.py          # 多模型并行跑分执行器
├── frontend/
│   ├── index.html         # 前端页面（HTML+CSS+JS 单体，自洽运行）
│   └── vendor/
│       └── html2pdf.bundle.min.js  # PDF 导出渲染库（本地化，离线可用）
├── scripts/
│   └── download_datasets.py  # 从 HuggingFace 拉取并转存 JSONL 数据集
├── data/sessions/         # 会话数据存储（JSON）
└── run.sh                 # 启动脚本（支持 prepare 子命令）
```

> 注：前端的 CSS 与 JS 全部内联于 [index.html](frontend/index.html)，无独立样式表或脚本文件被引用；如需拆分为外部文件请同步更新 `<style>`/`<script>` 引用关系。

## 研究流程

1. **规划**：LLM 分析问题，生成 2-4 个搜索关键词
2. **搜索**：多引擎并行搜索（百度/Google/Scholar/arXiv），抓取结果页面内容
3. **提取**：LLM 从每个网页提取与问题相关的关键事实
4. **综合**：LLM 综合所有资料，生成结构化研究报告（含来源引用）

## 搜索引擎

| 引擎 | 类型 | 说明 |
|------|------|------|
| `baidu` | 网页搜索 | 百度搜索，中文内容覆盖好 |
| `google` | 网页搜索 | Google 搜索，英文和全球信息覆盖广 |
| `scholar` | 学术搜索 | Google Scholar，学术论文和引用信息 |
| `arxiv` | 学术搜索 | arXiv API，预印本论文，无需页面抓取 |

通过环境变量 `DR_SEARCH_ENGINES` 可自由组合，例如只启用学术搜索：`DR_SEARCH_ENGINES=scholar,arxiv`

## 记忆系统

- **短期记忆**：保留最近 N 条对话消息
- **长期记忆**：消息过多时自动摘要压缩，保留关键信息
- **研究资料**：跨对话积累的研究事实和来源，持续可用

## 评测系统

通过 WebSocket `/ws/eval` 流式推送进度。每个待测模型使用独立的 LLMClient 实例（共享全局 base_url/api_key 或单独覆盖），并行答题后由 [eval/prompts.py](eval/prompts.py) 抽取答案并与标准答案比对判分。结果按模型汇总整体准确率及各学科分布，持久化到 `data/evals/{id}.json`，可在前端查看逐题 case 对比。
