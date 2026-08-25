<div align="center">

<a href="#"><img src="frontend/public/honey-logo.png" width="96" alt="HoneyDesk 蜜方 logo" /></a>

# HoneyDesk 蜜方 · 跨境电商 Multi-Agent 个人工作台

**以人机协作为核心的跨境电商个人工作台，用大白话向 AI 下达指令，即可完成查数、分析、写数据库与效果复盘。**

Python · FastAPI · LangGraph ｜ React 18 · TypeScript · Ant Design 5 ｜ MySQL 8.0 · Qdrant

</div>

---

## 目录

- [✨ 项目简介](#-项目简介)
- [🚀 核心能力](#-核心能力)
- [🛠 技术架构](#-技术架构)
- [📁 目录结构](#-目录结构)
- [🧭 快速上手（本地开发）](#-快速上手本地开发)
- [🐳 Docker 部署](#-docker-部署)
- [⚙️ 环境配置说明](#️-环境配置说明)
- [🗄 数据库与测试数据](#-数据库与测试数据)
- [🧪 开发者：重新生成 / 校验测试数据](#-开发者重新生成--校验测试数据)
- [🧠 Multi-Agent 与审批安全](#-multi-agent-与审批安全)
- [📖 常见问题 FAQ](#-常见问题-faq)
- [🤝 贡献与开源](#-贡献与开源)

---

## 界面预览

打开仓库根目录的 **`UI风格预览.html`**（浏览器直接打开），可预览浅色「微光·清新」与深色「臻选·醇厚」两套界面主题。

| 浅色「微光·清新」 | 深色「臻选·醇厚」 |
| --- | --- |
| 柔和薄荷绿 + 清爽白底 | 醇厚深棕 + 蜜金色调 |

界面上方为产品**蜂巢 logo**，同时用作侧栏品牌标识、用户头像与浏览器 favicon。

---

## ✨ 项目简介

HoneyDesk 蜜方面向**跨境电商个人卖家 / 运营**：把日常需要在 ERP / 后台手动的重复工作，改为用自然语言向工作台里的多个子 Agent 下达指令，Agent 自主完成：

- **查询**：如「近 14 天美国站日均广告花费是多少？」
- **分析**：如「分析近 14 天广告 ROI 并按商品排行」
- **写操作**：如「为表现最好的美妆 SKU 生成英文 Listing」「上调安全库存补货点」——**所有写数据库操作都必经人工审批**，可取消、拒绝、审计。
- **监控预警**：业务增长点 / 风险点自动识别并沉淀为产物，可跨 Agent 注入协同。

> 当前各 Agent 可交互操作的对象是**本地项目数据库**，不直接对接外部平台 API。写操作以「数据库记录变更」为唯一执行形态（例如"发布 Listing"= 更新 `listings` 表状态字段），因此**上手即可安全体验完整闭环，无需任何平台授权**。

---

## 🚀 核心能力

### Multi-Agent 编排（LangGraph）
四类子 Agent 聚焦各自业务板块，通过统一「意图识别 → 路由 → 状态机 → 工具编排 → 结果汇总」调度中心协作：

| Agent | 聚焦板块 |
| --- | --- |
| 🛒 运营 Agent | 商品 / Listing 查询问答与生成 |
| 📋 Listing Agent | Listing 文案生成、合规审查 |
| 🔗 供应链 Agent | 库存、补货、仓库维度的分析 |
| 🎯 广告 Agent | 广告投放 ROI / 预算分析 |

### 自然语言驱动 + 全链路留痕
- 对话式调度中心，支持 SQL 结果**表格 + ECharts 图表**可视化。
- 同一操作 ID 贯穿「意图 → 审批 → 执行 → 留痕」，写操作 100% 留痕（变更前后值）。
- 产物自动沉淀到**产物中心**，可挑选注入到任意 Agent / 会话。

### 本地知识库 RAG
- 文档 / 业务表一键索引 → 切分 →（可选）BGE-M3 向量化 → Qdrant 存储 → **BM25 + 向量 RRF 融合 + BGE-rerank 重排**。
- 未安装本地向量模型时自动降级为内置轻量 Embedding，RAG 闭环依然可用。

### 数据看板
任务总数 / 完成率、工具调用次数 / 成功率、知识库检索、Token 消耗等六大指标卡片 + 趋势图。

### 界面体验（近期重点优化）
- **主题自由切换**：浅色「微光·清新」+ 深色「臻选·醇厚」+ 跟随系统，在「系统设置」中一键切换并自动记忆。
- **品牌化设计**：蜂巢产品 logo（侧栏 / 用户头像 / 浏览器 favicon）。
- **清新的 Agent 标识**：多色柔和标签区分不同 Agent，深色下自动压暗降饱和，避免刺眼。
- 对话气泡、提示框、看板卡片、Agent 标签等在所有主题下均保持一致的可读性。

### 数据引擎（便于开箱即有真实业务感）
- **多店铺 / 多市场 / 多仓库 / 多币种**的业务数据模型，覆盖 Amazon / TikTok / Walmart，US / CA / DE / UK 等市场。
- **每日动态补数**：后端启动时自动把时序表补齐到今天，保证看板与分析的「当日 / 昨日」数据永远存在。

---

## 🛠 技术架构

| 层 | 方案 |
| --- | --- |
| 大模型 LLM | 用户自定义，**OpenAI 兼容协议**即可（OpenAI / 通义 / DeepSeek / 本地 Ollama / vLLM …），不锁定厂商 |
| 向量化（可选） | **BGE-M3**（本地推理，1024 维）；未安装自动降级为内置轻量 Embedding |
| 重排（可选） | BGE-reranker（cross-encoder） |
| 检索 | BM25 + 向量召回 → **RRF 融合** → BGE-rerank |
| 向量库 | **Qdrant 1.x**（Docker 单机） |
| 多 Agent | **LangGraph** |
| 后端 | FastAPI + SQLAlchemy 2 + PyMySQL |
| 存储 | **MySQL 8.0 分库**：`honey_desk` 业务库 + `honey_system` 系统库 |
| 前端 | React 18 + TypeScript + Ant Design 5 + ECharts + Vite |
| 部署 | Docker Compose 编排（Qdrant / Backend / Frontend），数据存本机 MySQL |

---

## 📁 目录结构

```
HoneyDesk蜜方/
├── docker-compose.yml          # Qdrant + 后端 + 前端
├── .env.example                # 环境配置模板（复制为 .env）
├── UI风格预览.html             # 主题/界面风格设计预览
├── README.md
├── backend/                    # Python FastAPI + LangGraph
│   ├── Dockerfile
│   ├── requirements.txt        # 核心依赖
│   ├── requirements-ml.txt     # 可选：BGE 本地向量/重排模型
│   ├── app/
│   │   ├── main.py             # FastAPI 入口（启动自动建表/种子/每日补数）
│   │   ├── config.py           # 配置（.env 读取）
│   │   ├── api/                # REST 路由
│   │   ├── scheduler/          # LangGraph 调度中心（意图/路由/状态机）
│   │   ├── agents/             # 业务子 Agent
│   │   ├── approval/           # 审批流（写操作）
│   │   ├── audit/              # 操作留痕
│   │   ├── artifacts/          # 产物中心
│   │   ├── dashboard/          # 数据看板聚合
│   │   ├── knowledge/ rag/     # 知识库 + 检索
│   │   ├── tools/              # 字段驱动工具注册表
│   │   ├── data/supply.py      # 每日动态补数
│   │   ├── imports/            # 数据导入
│   │   ├── ml/                 # 向量模型封装（可选）
│   │   ├── models/             # SQLAlchemy 模型（业务 + 系统）
│   │   └── seed.py             # 支撑表幂等种子（店铺/Agent/工具/设置）
│   └── db/
│       ├── schema_v2.sql       # ★ 一键测试数据（多店铺/市场/仓库，约 1.5 万行）
│       ├── gen_schema_v2.py    # 从 ORM 重新生成 schema_v2.sql
│       ├── validate_v2.py      # 校验 DDL 与 ORM / 关联键一致性
│       └── _smoke_v2.py        # 冒烟：实际导入测试库验证
└── frontend/                   # React 18 + TS + Ant Design 5
    ├── Dockerfile
    ├── public/                 # 静态资源（含 honey-logo.png favicon）
    └── src/                    # pages / components / api / theme
```

---

## 🧭 快速上手（本地开发）

### 0. 前置要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.11+ | 后端 |
| Node.js | 18+ | 前端 |
| MySQL | 8.0 | **本机安装**，业务与系统数据存放于此 |
| Docker（可选） | - | 只需二选一：仅起 Qdrant，或直接整栈部署 |
| 大模型 API | 任意 | 支持 OpenAI 兼容协议即可 |

> **MySQL 是唯一需要装在本机的中间件**：业务/系统数据（订单、库存、广告、对话、日志等）不走容器，请勿用 MySQL 容器。

### ① 准备本机 MySQL 并一键灌入测试数据

本机 `mysql` 命令行执行（该 SQL 会自动**创建两个库并建表灌数据**）：

- **`honey_desk`（业务库）**：`products / product_materials / listings / sales_orders / competitors / inventory / ad_performance / ad_budgets`，共约 **1.5 万行**、每张 ≥ 1000 行，时间跨度 **2025-07-01 → 2026-08**（> 1 年），聚焦美妆单品，覆盖多店铺 / 多市场 / 多仓库 / 多币种；
- **`honey_system`（系统库）**：`stores / agents / tools / chat_messages / tasks / approvals / approval_records / artifacts / audit_logs / kb_documents / memories / settings / linkage_events`（运行期写入）。

```bash
# cmd 执行（勿用 PowerShell 重定向，会破坏 UTF-8 编码）
mysql --default-character-set=utf8mb4 -u root -p < backend/db/schema_v2.sql
```

> SQL 已做**纯 ASCII** 编码（中文经 `CONVERT(X'<hex>' USING utf8mb4)` 写入），自动规避客户端本地字符集导致的乱码 / ERROR 1366。

### ② 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，重点填写：
- **大模型**：`LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`（OpenAI 兼容协议任意厂商）；
- **MySQL**：`MYSQL_USER` / `MYSQL_ROOT_PASSWORD`（填你本机 root 密码）/ `MYSQL_HOST=localhost`。

> 本机 MySQL root 密码默认为 `honeydesk_root`（代码默认值）；若与你的不一致，务必在 `.env` 中覆盖，否则后端无法连接。

### ③ 启动后端

```bash
cd backend

# （可选）虚拟环境
python -m venv .venv
# Windows: .venv\Scripts\activate   |  Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
# 可选：安装 BGE 本地向量/重排模型（提升语义检索，未装自动降级）
# pip install -r requirements-ml.txt

# 启动前先起 Qdrant（二选一）
docker compose up -d qdrant       # 或本机直接运行 qdrant 二进制

uvicorn app.main:app --reload --port 8000
```

> 启动时后端会自动完成：**幂等建表 → 支撑表种子 → 每日数据补数**，无需额外手动初始化。

### ④ 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173（/api 已代理到 8000）
```

### ⑤ 开始使用

1. 打开 **http://localhost:5173**；
2. 进「系统设置」填写并测试你的 LLM 连接；
3. 进「知识库管理」一键索引各业务表（接入 RAG 对话召回）；
4. 到「调度中心」对话，例如：
   - _「分析近 14 天广告 ROI 并给出优化建议」_
   - _「为表现最好的美妆 SKU 生成英文 Listing」_（写操作会进审批流，在右上角「审批待办」处理）。

**地址速览**

| 服务 | 地址 |
| --- | --- |
| 前端工作台 | http://localhost:5173 |
| 后端 API 文档 | http://localhost:8000/docs |
| Qdrant 控制台 | http://localhost:6333 |
| MySQL | localhost:3306 |

---

## 🐳 Docker 部署

> Docker Compose 只编排 **Qdrant / Backend / Frontend** 三个服务；**MySQL 仍为本机安装**，且需先完成①的建库灌数据。

```bash
# 1. 本机 MySQL 先导入测试数据（见上文「准备 MySQL」）⚠️ 必做
mysql --default-character-set=utf8mb4 -u root -p < backend/db/schema_v2.sql

# 2. 配置环境变量
cp .env.example .env
#    编辑 .env：填入 LLM key，并把 MYSQL_HOST 改为 host.docker.internal（容器连本机 MySQL 用）

# 3. 一键启动 Qdrant + 后端 + 前端
docker compose up -d --build
```

- 后端容器内置**宿主机 MySQL 免手动 seed**：启动时自动建表 + 种子支撑表 + 每日补数，仅业务大数据需要手动导入；
- 若前端 `5173` 未生效，请强刷（Ctrl+F5）以越过浏览器缓存旧编译产物。

---

## ⚙️ 环境配置说明

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_API_BASE` | 空 | LLM Endpoint，OpenAI 兼容协议（OpenAI / 通义 / DeepSeek / Ollama …） |
| `LLM_API_KEY` | 空 | LLM API Key |
| `LLM_MODEL` | 空 | 主模型 |
| `LLM_LIGHT_MODEL` | 空 | 可选轻量模型（意图识别等），留空则统一走主模型 |
| `EMBEDDING_MODEL_PATH` | `models/bge-m3` | 可选 BGE 向量模型目录 |
| `EMBEDDING_BACKEND` | `auto` | `auto` / `bge` / `fallback` |
| `MYSQL_HOST` | `localhost` | 本机运行 `localhost`；Docker 连本机 MySQL 用 `host.docker.internal` |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `root` | MySQL 用户 |
| `MYSQL_ROOT_PASSWORD` | `honeydesk_root` | MySQL 密码（务必覆盖为你的实际密码） |
| `MYSQL_DATABASE` | `honey_system` | 连接默认库（所有表均以 schema 限定，默认库仅需存在） |
| `QDRANT_HOST` / `QDRANT_PORT` | `localhost` / `6333` | 向量库 |
| `QDRANT_COLLECTION` | `honeydesk_kb` | 知识库集合名 |
| `APP_PORT` | `8000` | 后端端口 |
| `APPROVAL_TIMEOUT_HOURS` | `24` | 审批超时挂起时长 |
| `RAG_TOP_K` | `5` | 检索返回条数 |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 允许的前端来源 |

---

## 🗄 数据库与测试数据

### 分库设计

- **`honey_desk` 业务库**：商品 / 产品资料 / Listing / 销售订单 / 竞品快照 / 库存 / 广告数据 / 广告预算；
- **`honey_system` 系统库**：店铺 / Agent / 工具 / 对话 / 任务 / 审批 / 产物 / 审计 / 知识库 / 记忆 / 设置 / 联动事件。

所有表均以 **schema 限定前缀**访问，建表由 SQLAlchemy 模型生成，保证 DDL 与后端字段完全一致。

### 每日动态补数

后端启动时调用 `backend/app/data/supply.py::supply_missing_daily`：

- 自动扫描各时序表最新日期，把缺失日期**逐日补齐到今天**（与历史日均规模一致）；
- 就地刷新库存至当日、按当月补齐广告预算；
- **幂等**（按日期判重），失败不阻断启动。

因此即使长期不重新导数据，看板 / 时序分析的「当日、昨日」数据也始终存在。

### 测试数据说明（schema_v2.sql）

由 `gen_schema_v2.py` 从 ORM 反射生成，维度覆盖：

- **5 个店铺**（Amazon / TikTok / Walmart × US / CA / DE）；
- **多仓库**（US-LAX / US-JFK / CA-VAN / DE-FRA / UK-LIV / CN-SH，海外仓 + 国内仓）；
- **多市场、多币种**（USD / CAD / EUR）与多语言；
- 表间通过 `store_id` / `sku` / `market` 保持主外键一致（`validate_v2.py` 会校验）。

---

## 🧪 开发者：重新生成 / 校验测试数据

> 以下为开发者可选步骤，通常无需执行——仓库已内置生成好的 `schema_v2.sql`。

```bash
cd backend

# 1) 从 ORM 重新生成 schema_v2.sql（覆盖 backend/db/schema_v2.sql）
python db/gen_schema_v2.py

# 2) 校验 DDL 与 ORM 是否一致 + 跨表关联键是否匹配
python db/validate_v2.py

# 3) 冒烟：实际导入临时测试库，验证 SQL 语法与数据可落库
python db/_smoke_v2.py

# 4) 检查每日补数逻辑（需已配置 MYSQL_HOST / MYSQL_USER / MYSQL_ROOT_PASSWORD 环境变量）
python db/_verify_supply.py
```

---

## 🧠 Multi-Agent 与审批安全

- 写操作进入**审批流**：待审批 → 通过 / 拒绝 / 超时挂起，审批详情含目标表 / 字段 / **变更前后值 diff** / 依据；
- 审计与业务数据同库存储，但通过「应用层只读约束 + 追加式写入」保证**只读防篡改**（REST 层仅暴露查询，无更新 / 删除接口）；
- 同一操作 ID 贯穿「意图 → 审批 → 执行 → 留痕」全链路；
- 工具集**字段驱动**：业务表有哪些字段才生成哪些工具，未导入字段不提供工具，降低误操作面。

---

## 📖 常见问题 FAQ

**Q1：后端连不上 MySQL（1045 / 2003）**
检查 `.env` 的 `MYSQL_ROOT_PASSWORD` 是否为你的本机实际密码；`MYSQL_HOST` 本地运行用 `localhost`，Docker 运行用 `host.docker.internal`。

**Q2：导入 SQL 提示编码 / 语法错误**
使用 `cmd`（而非 PowerShell）执行，并务必带 `--default-character-set=utf8mb4`；见上文导入命令。

**Q3：对话检索不到知识库内容**
进「知识库管理」先对业务表执行一次「一键索引」，写入 Qdrant 后再去对话。

**Q4：是否必须安装 BGE 本地模型？**
不必。未安装会自动降级为内置轻量 Embedding，核心闭环可用；追求更好的语义检索质量再安装 `requirements-ml.txt` 并设置 `EMBEDDING_BACKEND=bge`。

**Q5：前端白屏 / 旧代码不生效**
浏览器缓存了旧编译产物。请 **Ctrl+F5 强刷** 或清除站点数据后再加载。

---

## 🤝 贡献与开源

欢迎 Star、Issue 与 PR！

- 功能建议 / 体验优化 → [Issues](https://github.com/) 新建讨论；
- 代码贡献：Fork → 新建分支 → 提交 PR。

> ⚠️ 请勿在提交中夹带 `.env`（含你的 API Key / 数据库密码）。仓库已通过 `.gitignore` 忽略 `.env`、`__pycache__`、`node_modules`、`dist` 与本地模型目录。