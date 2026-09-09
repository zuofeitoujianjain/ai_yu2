<div align="center">

# 🐋 aiyu · QQ 群 AI 聊天机器人（邪恶鲸鱼娘）

**登录你自己的 QQ 小号，在群里被 `@邪恶鲸鱼娘` 时，由 DeepSeek 以角色人设自动回复。**

基于 OneBot v11 协议 + DeepSeek 大模型，从协议对接 → 消息解析 → 工具/路由/记忆 → 管理面板/热更新 → Docker 部署的**全栈实现**。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%2F%20Docker-orange)](https://www.docker.com/)
[![Protocol](https://img.shields.io/badge/Protocol-OneBot%20v11-purple)](https://github.com/botuniverse/onebot-11)

</div>

---
<div>
    

</div>
---
## 📖 项目简介

`aiyu` 是一个**可登录个人 QQ 账号**的群聊 AI 机器人。群里发 `@邪恶鲸鱼娘 + 内容`，机器人提取 **@ 之后的文字**，交给 DeepSeek 生成「邪恶鲸鱼娘」人设的回复并回发。

它解决了这类项目的核心痛点：**腾讯官方不开放个人 QQ 账号的群消息 API**。本项目用 **OneBot v11 正向 WebSocket** 对接能登录 QQ 的协议实现（NapCat），把「登录 QQ + 收发消息」和「AI 回复业务」彻底解耦，并围绕它做了一整套**可配置、可观测、可迁移**的能力。

> ⚠️ **风险提示**：依赖 NapCat 等第三方协议实现登录 QQ，**违反腾讯用户协议**，存在封号风险。**强烈建议用小号运行**。仅供学习交流。

---

## ✨ 功能特性

### 🎯 交互体验（A 组）
- **@ 触发**：只响应群里 `@机器人`，精准提取 @ 之后的文本；兼容 CQ 码字符串与消息段数组**双格式**（@全体成员不误触发）
- **免@对话（按用户）**：某用户 @ 过机器人后进入该群**免@窗口**，窗口内 TA 免 @ 直接聊
- **关键词触发**：消息命中 `trigger_keywords`（默认"鱼/鲸鱼"）自动回发送者并进入免@窗口
- **限流冷却**：同一用户 `cooldown_seconds` 内重复触发**静默忽略**，防刷屏
- **指令系统**：`/help`、`/人设 <名>`、`/画像`、`/记忆`、`/开关 <功能>`
- **人设切换接口**：`@机器人 切换人设 人设名` 一句话切换人格
- **多角色 / 多群独立人设**：每群可独立切换人设（内置默认"邪恶鲸鱼娘"+ 示例"永雏塔菲"）

### 🧠 记忆与人格（B / D 组）
- **用户画像**：记录每人各群的**群名片 + 常用话题**（bigram 词频），对话时注入「资料卡」让模型"认识"对方
- **独立会话记忆**：按「群 + 人」维护最近 N 轮上下文；「清空记忆」关键词重置
- **长期记忆**：`memory.json` 持久化 + **bigram 相似度召回**，**跨会话/重启**记住前因后果；`/记忆` 查看/清空

### ⚡ AI 能力进阶（C 组）
- **智能路由**：简单问题走 `deepseek-chat`（快），命中关键词或超长自动切 `deepseek-reasoner`（会思考）
- **工具调用 / Agent 化**：模型自己决定调用工具并拿结果作答（免密钥）：**当前时间 / 天气(open-meteo) / 翻译 / 安全计算**（`ast` 白名单，杜绝任意代码执行）
- **联网搜索（可选，默认关）**：`web_search` 工具，支持**博查 Bocha**（国内直连、真实全网）或免密钥兜底；因国内免密钥源被墙/403，**默认关闭**，配好博查 key 后开启

### 📊 管理与可观测（F 组）
- **黑白名单权限**：群/用户 allow / block 过滤，白名单优先，**管理员绕过限制**
- **掉线 / 报错告警**：连接断开或 DeepSeek 接口报错，自动**私聊管理员**（限流防刷）
- **Web 管理面板**：进程内 aiohttp + token 认证，`127.0.0.1` 访问——在线查看**状态/日志/开关/人设/白名单**并实时切换

### 🛠️ 工程化（G 组）
- **配置热更新**：每 15 秒检测 `config.json`，行为类配置（人设/开关/阈值）**改完即生效，无需重启**
- **Docker 部署**：`bot + NapCat` 编排（docker-compose），密钥不入镜像
- **一键工具**：`启动ai鱼.bat` / `停止ai鱼.bat` / `一键安装.bat`（纯 ASCII 壳 + PowerShell EncodedCommand，无乱码）
- **跨机迁移**：免安装包、相对路径脚本、环境自检

---

## 🏗️ 工作原理

```mermaid
flowchart LR
    A[你的 QQ 小号] <--> B[NapCat Shell\n协议实现·登录QQ/收发消息]
    B <-->|OneBot v11 正向 WebSocket| C[bot.py\nPython asyncio + aiohttp]
    C <-->|OpenAI 兼容接口| D[DeepSeek API\ndeepseek-chat / reasoner]
    C -. 工具: 时间/天气/翻译/计算/搜索 .-> E[外部服务]
    C -. 记忆: memory.json 持久化 .-> F[本地存储]
    B -.监听 ws://127.0.0.1:3001 .-> C
```

- **连接层** NapCat：登录 QQ 并转成标准 OneBot v11 事件，执行发消息等动作。
- **业务层** bot.py：客户端连上 NapCat，接收消息 → 解析 @ →（路由/工具/记忆/画像）→ 调 DeepSeek → 回发。
- **推理层** DeepSeek：OpenAI 兼容接口，多模型 + 函数调用。
- **可观测**：进程内 Web 面板（本机 + token）、告警私聊、配置热更新。

---

## 📁 目录结构

```
aiyu-bot/
├── bot.py                 # 机器人主程序（OneBot + 解析 + 路由/工具/记忆/画像 + 告警 + Web面板 + 热更新）
├── config.example.json    # 配置模板（复制为 config.json 后填写，勿提交真实配置）
├── requirements.txt       # 依赖（仅 aiohttp）
├── speedtest.py           # DeepSeek 接口测速脚本（排查回复慢）
├── Dockerfile             # 容器化（不含密钥）
├── docker-compose.yml     # bot + NapCat 编排
├── .dockerignore          # 排除密钥/文档/第三方
├── 启动ai鱼.bat / .ps1      # 一键启动（NapCat + 机器人）
├── 停止ai鱼.bat / .ps1      # 一键停止（按端口精准杀进程）
├── 一键安装.bat / .ps1      # 环境检查 + 装依赖
├── docs/
│   ├── 功能规划.md          # 功能清单 + 优先级 + 已完成
│   ├── 开发计划.md          # 任务分组 + 分批开发 + 统一测试
│   ├── 新功能开发Prompt.md  # 给 AI 提需求的模板
│   └── Docker部署.md        # 服务器部署指南
├── README.md
├── .gitignore             # 已排除含密钥的 config.json / memory.json
└── LICENSE                # MIT
```

---

## 🚀 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.10+ | 运行 bot.py |
| Node.js | LTS | NapCat Shell 需要 |
| QQ NT | 最新版 | 新版 QQ 客户端，先登录过一次 |

### Step 1：安装协议实现（NapCat）

NapCat 负责登录 QQ 并把消息转成 OneBot 协议（本项目**不内置** NapCat）：

1. 下载 [NapCatQQ Releases](https://github.com/NapNeko/NapCatQQ/releases) 的 **`NapCat.Shell.zip`**（或自带 Node 的 `NapCat.Shell.Windows.Node.zip`）；
2. 解压到本项目目录下 **`napcat\`**（需含 `launcher-user.bat`）；
3. 运行 `napcat\launcher-user.bat`，弹出 QQ 窗口**扫码登录**（小号）；
4. 打开 NapCat WebUI（默认 `http://127.0.0.1:6099/webui`）→「网络配置 → OneBot11」→ 开启 **WebSocket 服务器（正向）**，记下端口（默认 `3001`）和 access_token。

### Step 2：安装依赖

```bash
pip install -r requirements.txt
```

### Step 3：配置

```bash
copy config.example.json config.json     # Windows
cp config.example.json config.json        # Linux
```

必填 3 项：

```jsonc
{
  "bot_qq": "123456789",                    // 登录的 QQ 小号（纯数字）
  "onebot_access_token": "your-napcat-token",// Step1 记录的令牌
  "deepseek_api_key": "sk-xxxxxxxxxx"       // DeepSeek API Key（platform.deepseek.com）
}
```

### Step 4：运行

```bash
python bot.py --selftest     # 离线自测（消息解析/路由/工具/记忆/权限/热更新）
python bot.py                # 正式启动
```

看到 `✅ 已连接，开始监听消息` 后，群里发 `@邪恶鲸鱼娘 你好` 即可。

> 🐳 **一键方式**：配置好后双击 `启动ai鱼.bat` 同时拉起 NapCat 和机器人；退出 `停止ai鱼.bat`；新电脑环境检查 `一键安装.bat`。

---

## ⚙️ 配置项说明

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `onebot_ws_url` | `ws://127.0.0.1:3001` | OneBot 正向 WebSocket 地址（Docker 里填服务名） |
| `onebot_access_token` | `""` | NapCat 设置的访问令牌（不匹配则操作被拒） |
| `bot_qq` | `""` | **必填**，登录 QQ 号 |
| `deepseek_api_key` | `""` | **必填**，DeepSeek Key |
| `deepseek_model` / `model_reasoner` | `deepseek-chat` / `deepseek-reasoner` | 快速 / 思考模型（路由用） |
| `system_prompt` | 鲸鱼娘人设 | 默认人设（**在此编辑人格**） |
| `personas` | `{高冷, 永雏塔菲...}` | 可切换人设库；`/人设 <名>` 或 `@ 切换人设 <名>` |
| `trigger_keywords` | `[鱼, 鲸鱼]` | 关键词触发列表 |
| `auto_reply_window_minutes` | `3` | 免@窗口时长（分钟） |
| `cooldown_seconds` | `10` | 每用户限流冷却（秒） |
| `router_enabled` / `router_reasoner_keywords` / `router_long_threshold` | `true` / … / `60` | 智能路由：关键词或超过 N 字切思考模型 |
| `enable_tools` / `tool_max_iterations` | `true` / `3` | 工具调用开关 / Agent 最多轮数 |
| `enable_web_search` / `search_provider` / `search_api_key` | `false` / `""` / `""` | 联网搜索（关）；`bocha`=博查(国内直连)，填 key 后开 |
| `memory_enabled` / `memory_file` / `memory_max_entries` / `memory_recall_topk` | `true` / `memory.json` / `50` / `3` | 长期记忆 |
| `admin_qq` | `""` | 管理员 QQ（掉线/报错告警接收人，填了才发） |
| `alert_on_disconnect` / `alert_on_api_error` / `alert_throttle_seconds` | `true` / `true` / `120` | 告警开关 |
| `allowed_groups` / `blocked_groups` / `allowed_users` / `blocked_users` | `[]` | 黑白名单（白名单非空则只放行名单内） |
| `web_enabled` / `web_host` / `web_port` / `web_token` | `true` / `127.0.0.1` / `8200` / `""` | Web 面板（**仅本机 + token**） |
| `history_limit` / `temperature` / `max_tokens` / `api_timeout` | `20` / `1.0` / `1024` / `180` | 记忆轮数 / 随机度 / 回复长度 / 接口超时 |

> **热更新**：改上述**行为类**配置后约 15 秒生效（无需重启）；仅连接/密钥类（`ws_url`/`token`/`bot_qq`/`api_key`）需重启。

---

## 🎭 人设与指令

可用指令：

| 指令 | 作用 |
| --- | --- |
| `/help` | 查看帮助 |
| `/人设` | 查看可用人设 |
| `/人设 <名>` | 切换本群人设 |
| `@我 切换人设 <名>` | 一句话切换本群人设 |
| `/画像` | 查看你的资料卡 |
| `/记忆` · `/记忆 清空` | 查看 / 清空长期记忆 |
| `/开关 <关键词·指令·私聊>` | 开关功能 |

**新增人设**：在 `config.json` 的 `personas` 里加一条 `{ "名字": "系统提示人设" }`，保存即热生效。已内置示例 `高冷`、`永雏塔菲`。

---

## 🖥️ Web 管理面板

配置好 `web_token` 后，浏览 `http://127.0.0.1:8200` 并用 token 登录（本地令牌认证）：

| 接口 | 说明 |
| --- | --- |
| `GET /api/status` | 连接 / 消息数 / 错误数 / 记忆条数 / 运行时长 |
| `GET /api/state` | 运行开关 + 人设 + 白名单 |
| `GET /api/logs` | 最近日志（环形缓冲） |
| `POST /api/toggle` | 在线开关（关键词/指令/私聊/工具/路由/记忆） |
| `POST /api/persona` | 设群/默认人设 |
| `POST /api/whitelist` | 改黑白名单 |

> 仅监听 `127.0.0.1`，请勿改成 `0.0.0.0`，避免局域网/公网控制。

---

## 🐳 Docker 部署

```bash
docker compose up -d --build
```

- `bot` 容器只含 `bot.py` + 依赖；`config.json`、`memory.json` 用 volume 挂载（改配置不丢、密钥不入镜像）。
- 容器内 `onebot_ws_url` 用服务名 `ws://napcat:3001`。
- 首次打开 `http://<主机>:6099/webui` 扫码登录 NapCat，并在 OneBot11 开启 WebSocket 3001。
- 详见 `docs/Docker部署.md`。

---

## 📊 性能参考（本机实测）

| 场景 | 耗时 |
| --- | --- |
| 网络往返（不含生成） | ~1.2s |
| 50 字回复 | ~1.3s |
| 200 字回复 | ~2.8s |
| 20 轮历史对话 | ~1.9s |

> 回复长度是最大耗时因素（`speedtest.py` 可一键定位瓶颈）。

---

## ❓ 常见问题

- **双击启动没反应/乱码**：脚本已做纯 ASCII 壳 + PowerShell EncodedCommand，规避编码问题。
- **连接被拒绝**：NapCat 没起或 QQ 没登录；确认端口 3001 监听、令牌两边一致。
- **群里 @ 没反应**：`bot_qq` 填登录账号（非昵称）。
- **回复"深海信号不好"**：DeepSeek 调用失败（401=Key错/没余额，429=限流）；Web 面板可看错误数和日志。
- **日志刷 `[Rkey] 异常`**：NapCat 第三方图片服务失效，**不影响文字聊天**，可忽略或升级 NapCat。
- **账号被风控/封禁**：非官方协议固有风险，只能换小号、控频率。

---

## ⚠️ 免责声明

- 仅用于技术学习与交流，请勿违法违规用途。
- 使用第三方协议实现登录 QQ 违反腾讯用户协议，**存在封号风险**，请自行评估并仅用小号运行。
- 本仓库**不含**任何真实账号、API Key、令牌（`.gitignore`/`.dockerignore` 已兜底）。

---

## 🗺️ Roadmap

- [ ] E 组：定时推送 / 进群欢迎 / 群摘要（AI 复盘）
- [ ] 图片理解（多模态模型）
- [ ] 语音回复
- [ ] 真·语义向量记忆（接 embedding 模型 / chromadb）
- [ ] 多模型接入（Qwen / GPT / 本地模型）

> 详见 `docs/功能规划.md`（含优先级与完成清单）、`docs/开发计划.md`（分组开发 + 统一测试）。

---

## 📄 许可证

[MIT](LICENSE)
