# Docker 部署指南（aiyu 机器人 + NapCat）

> 适用：Linux 服务器 / 本机 Docker。Windows 本地用回 `启动ai鱼.bat` 即可。

## 前提

- 已装 Docker / Docker Compose
- 一个 QQ 小号 + DeepSeek API Key
- 在项目根目录（含 `Dockerfile`、`docker-compose.yml`、`bot.py`）操作

## 步骤

1. **准备配置**：把 `config.example.json` 复制为 `config.json`，并**调整一处**：
   ```jsonc
   "onebot_ws_url": "ws://napcat:3001"   // ← 容器内用服务名 napcat，不是 127.0.0.1
   ```
   填好 `bot_qq`、`deepseek_api_key`、`onebot_access_token`（NapCat 登录后 WebUI 里设）。

2. **启动**：
   ```bash
   docker compose up -d --build
   ```

3. **登录 NapCat**：浏览器打开 `http://<主机IP>:6099/webui`（令牌见 `napcat-config/webui.json`），扫码登录小号；在「网络配置 → OneBot11」开启 **WebSocket服务器(正向)** 端口 **3001**。

4. **看日志**：
   ```bash
   docker logs -f aiyu-bot
   ```
   出现 `✅ 已连接，开始监听消息` 即成功。

## 说明

- `bot` 容器只含 `bot.py` + 依赖；`config.json`、`memory.json` 用 volume 挂载，改配置/记忆**不丢**、无需 rebuild。
- 改 `config.json` 里的**行为类**配置（人设、开关、阈值等）后，机器人有**配置热更新**（约 15 秒检测一次，自动生效，无需重启）。连接/密钥类（ws_url、token、bot_qq、api_key）仍需重启。
- 若不想要 NapCat 容器，只用 `docker build -t aiyu-bot .` + `docker run` 连接你已有的 NapCat。
- 存储：`napcat-config/`、`memory.json` 会随目录保留，方便迁移。
