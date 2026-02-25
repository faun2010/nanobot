<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot：超轻量个人 AI 助手</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** 是一款受 [Clawdbot](https://github.com/openclaw/openclaw) 启发的**超轻量**个人 AI 助手。

⚡️ 仅用 **~4,000** 行代码实现核心 Agent 功能，相比 Clawdbot 的 43 万+ 行代码体量缩小 **99%**。

📏 实时代码行数：**3,448 行**（可随时运行 `bash core_agent_lines.sh` 验证）

## 📢 最新动态

- **2026-02-08** 🔧 重构了 Providers，新增 LLM Provider 现在只需 2 个简单步骤！见[这里](#providers)。
- **2026-02-07** 🚀 发布 v0.1.3.post5，支持 Qwen 并包含多项关键改进！详情见[这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post5)。
- **2026-02-06** ✨ 新增 Moonshot/Kimi Provider、Discord 集成，并加强安全加固！
- **2026-02-05** ✨ 新增飞书渠道、DeepSeek Provider，并增强定时任务支持！
- **2026-02-04** 🚀 发布 v0.1.3.post4，支持多 Provider 与 Docker！详情见[这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4)。
- **2026-02-03** ⚡ 集成 vLLM 以支持本地 LLM，并改进自然语言任务调度能力！
- **2026-02-02** 🎉 nanobot 正式发布！欢迎体验 🐈 nanobot！

## nanobot 核心特点

🪶 **超轻量**：核心 Agent 代码仅 ~4,000 行，比 Clawdbot 小 99%。

🔬 **科研友好**：代码简洁、可读性高，易于理解、修改与扩展。

⚡️ **极速运行**：体积小意味着启动更快、资源占用更低、迭代更迅速。

💎 **开箱即用**：一键部署即可开始使用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot architecture" width="800">
</p>

## ✨ 功能

<table align="center">
  <tr align="center">
    <th><p align="center">📈 7x24 实时市场分析</p></th>
    <th><p align="center">🚀 全栈软件工程师</p></th>
    <th><p align="center">📅 智能日常管理</p></th>
    <th><p align="center">📚 个人知识助手</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">发现 • 洞察 • 趋势</td>
    <td align="center">开发 • 部署 • 扩展</td>
    <td align="center">排程 • 自动化 • 组织</td>
    <td align="center">学习 • 记忆 • 推理</td>
  </tr>
</table>

## 📦 安装

**从源码安装**（最新特性，推荐开发者）

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**使用 [uv](https://github.com/astral-sh/uv) 安装**（稳定、快速）

```bash
uv tool install nanobot-ai
```

**从 PyPI 安装**（稳定版）

```bash
pip install nanobot-ai
```

## 🚀 快速开始

> [!TIP]
> 在 `~/.nanobot/config.json` 中设置你的 API Key。
> 可在此获取： [OpenRouter](https://openrouter.ai/keys)（全球） · [DashScope](https://dashscope.console.aliyun.com)（Qwen） · [Brave Search](https://brave.com/search/api/)（可选，用于联网搜索）

**1. 初始化**

```bash
nanobot onboard
```

**2. 配置**（`~/.nanobot/config.json`）

面向全球用户，推荐 OpenRouter：
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

**3. 开始对话**

```bash
nanobot agent -m "What is 2+2?"
```

完成！2 分钟内即可拥有一个可用的 AI 助手。

## 🖥️ 本地模型（vLLM）

通过 vLLM 或任意兼容 OpenAI API 的服务，让 nanobot 运行在你自己的本地模型上。

**1. 启动 vLLM 服务**

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. 配置**（`~/.nanobot/config.json`）

```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

**3. 开始对话**

```bash
nanobot agent -m "Hello from my local LLM!"
```

> [!TIP]
> 对于不需要鉴权的本地服务，`apiKey` 可以填写任意非空字符串。

## 💬 聊天应用

你可以通过 Telegram、Discord、WhatsApp 或飞书随时随地与 nanobot 对话。

| 渠道 | 配置难度 |
|---------|-------|
| **Telegram** | 简单（仅需 token） |
| **Discord** | 简单（bot token + intents） |
| **WhatsApp** | 中等（需扫码） |
| **Feishu** | 中等（需应用凭证） |

<details>
<summary><b>Telegram</b>（推荐）</summary>

**1. 创建机器人**
- 打开 Telegram，搜索 `@BotFather`
- 发送 `/newbot`，按提示完成创建
- 复制 token

**2. 配置**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

> 你可通过 Telegram 的 `@userinfobot` 获取自己的 user ID。

**3. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Discord</b></summary>

**1. 创建机器人**
- 打开 https://discord.com/developers/applications
- 创建应用 → Bot → Add Bot
- 复制 bot token

**2. 启用 intents**
- 在 Bot 设置中启用 **MESSAGE CONTENT INTENT**
- （可选）如果你计划基于成员信息使用 allow list，请启用 **SERVER MEMBERS INTENT**

**3. 获取你的 User ID**
- Discord 设置 → Advanced → 启用 **Developer Mode**
- 右键你的头像 → **Copy User ID**

**4. 配置**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**5. 邀请机器人**
- OAuth2 → URL Generator
- Scopes: `bot`
- Bot Permissions: `Send Messages`, `Read Message History`
- 打开生成的邀请链接，将机器人加入你的服务器

**6. 运行**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

需要 **Node.js ≥18**。

**1. 关联设备**

```bash
nanobot channels login
# 在 WhatsApp 中扫码：Settings → Linked Devices
```

**2. 配置**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

**3. 运行**（两个终端）

```bash
# Terminal 1
nanobot channels login

# Terminal 2
nanobot gateway
```

</details>

<details>
<summary><b>Feishu（飞书）</b></summary>

采用 **WebSocket 长连接**，无需公网 IP。

**1. 创建飞书机器人**
- 访问 [Feishu Open Platform](https://open.feishu.cn/app)
- 创建新应用 → 启用 **Bot** 能力
- **Permissions**：添加 `im:message`（发送消息）
- **Events**：添加 `im.message.receive_v1`（接收消息）
  - 选择 **Long Connection** 模式（需要先运行 nanobot 建立连接）
- 在 “Credentials & Basic Info” 获取 **App ID** 和 **App Secret**
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": []
    }
  }
}
```

> 在 Long Connection 模式下，`encryptKey` 和 `verificationToken` 为可选。
> `allowFrom`：留空表示允许所有用户，或填写 `["ou_xxx"]` 以限制访问。

**3. 运行**

```bash
nanobot gateway
```

> [!TIP]
> 飞书通过 WebSocket 接收消息，不需要 webhook 或公网 IP！

</details>

<details>
<summary><b>DingTalk（钉钉）</b></summary>

采用 **Stream Mode**，无需公网 IP。

**1. 创建钉钉机器人**
- 访问 [DingTalk Open Platform](https://open-dev.dingtalk.com/)
- 创建新应用 -> 添加 **Robot** 能力
- **Configuration**：
  - 打开 **Stream Mode**
- **Permissions**：添加发送消息所需权限
- 在 “Credentials” 中获取 **AppKey**（Client ID）和 **AppSecret**（Client Secret）
- 发布应用

**2. 配置**

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "YOUR_APP_KEY",
      "clientSecret": "YOUR_APP_SECRET",
      "allowFrom": []
    }
  }
}
```

> `allowFrom`：留空表示允许所有用户，或填写 `["staffId"]` 以限制访问。

**3. 运行**

```bash
nanobot gateway
```

</details>

## ⚙️ 配置

配置文件：`~/.nanobot/config.json`

### Providers

> [!NOTE]
> Groq 提供免费的 Whisper 语音转写能力。完成配置后，Telegram 语音消息会自动转写。

| Provider | 用途 | 获取 API Key |
|----------|---------|-------------|
| `openrouter` | LLM（推荐，访问全模型） | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | LLM（Claude 官方） | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | LLM（GPT 官方） | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM（DeepSeek 官方） | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **语音转写**（Whisper） | [console.groq.com](https://console.groq.com) |
| `gemini` | LLM（Gemini 官方） | [aistudio.google.com](https://aistudio.google.com) |
| `aihubmix` | LLM（API 网关，访问全模型） | [aihubmix.com](https://aihubmix.com) |
| `dashscope` | LLM（Qwen） | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `moonshot` | LLM（Moonshot/Kimi） | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | LLM（智谱 GLM） | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `vllm` | LLM（本地，任意 OpenAI 兼容服务） | — |

<details>
<summary><b>新增 Provider（开发者指南）</b></summary>

nanobot 使用 **Provider Registry**（`nanobot/providers/registry.py`）作为唯一事实来源。
新增一个 Provider 仅需 **2 步**，无需修改 if-elif 链。

**步骤 1**：在 `nanobot/providers/registry.py` 的 `PROVIDERS` 中增加一条 `ProviderSpec`：

```python
ProviderSpec(
    name="myprovider",                   # 配置字段名
    keywords=("myprovider", "mymodel"),  # 用于自动匹配模型名的关键字
    env_key="MYPROVIDER_API_KEY",        # LiteLLM 使用的环境变量
    display_name="My Provider",          # 在 `nanobot status` 中展示
    litellm_prefix="myprovider",         # 自动前缀：model -> myprovider/model
    skip_prefixes=("myprovider/",),      # 避免重复加前缀
)
```

**步骤 2**：在 `nanobot/config/schema.py` 的 `ProvidersConfig` 中增加字段：

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

完成！环境变量、模型前缀、配置匹配以及 `nanobot status` 展示都会自动生效。

**常见 `ProviderSpec` 选项：**

| 字段 | 说明 | 示例 |
|-------|-------------|---------|
| `litellm_prefix` | 为 LiteLLM 自动补模型名前缀 | `"dashscope"` -> `dashscope/qwen-max` |
| `skip_prefixes` | 若模型名已以这些前缀开头则不再补前缀 | `("dashscope/", "openrouter/")` |
| `env_extras` | 需要额外注入的环境变量 | `(("ZHIPUAI_API_KEY", "{api_key}"),)` |
| `model_overrides` | 按模型覆盖参数 | `(("kimi-k2.5", {"temperature": 1.0}),)` |
| `is_gateway` | 是否可路由任意模型（如 OpenRouter） | `True` |
| `detect_by_key_prefix` | 按 API Key 前缀识别网关 | `"sk-or-"` |
| `detect_by_base_keyword` | 按 API Base URL 关键字识别网关 | `"openrouter"` |
| `strip_model_prefix` | 重加前缀前先去除已有前缀 | `True`（用于 AiHubMix） |

</details>


### 安全

> [!TIP]
> 生产部署建议在配置中设置 `"restrictToWorkspace": true`，将 Agent 运行范围限制在工作区内。

| 选项 | 默认值 | 说明 |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | 为 `true` 时，将 **所有** Agent 工具（shell、文件读写编辑、list）限制在工作区目录内，防止路径穿越和越界访问。 |
| `channels.*.allowFrom` | `[]`（允许所有） | 用户 ID 白名单。空数组表示允许所有人；非空则仅允许列表内用户交互。 |


## CLI 参考

| 命令 | 说明 |
|---------|-------------|
| `nanobot onboard` | 初始化配置与工作区 |
| `nanobot agent -m "..."` | 与 Agent 对话 |
| `nanobot agent` | 交互式聊天模式 |
| `nanobot gateway` | 启动网关 |
| `nanobot status` | 查看状态 |
| `nanobot channels login` | 关联 WhatsApp（扫码） |
| `nanobot channels status` | 查看渠道状态 |

<details>
<summary><b>定时任务（Cron）</b></summary>

```bash
# 添加任务
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# 查看任务
nanobot cron list

# 删除任务
nanobot cron remove <job_id>
```

</details>

## 🐳 Docker

> [!TIP]
> 建议使用独立目录 `~/.nanobot-docker` 作为 Docker 运行配置，和本地 CLI 调试目录 `~/.nanobot` 完全隔离。
> 默认 `docker-compose.yml` 会把当前仓库挂载到容器内：
> `/home/nanobot/.nanobot/workspace/nanobot-src`，便于让 nanobot 直接读取/修改源码。

在容器中构建并运行 nanobot：

```bash
export NB_UID="$(id -u)" NB_GID="$(id -g)"
mkdir -p ~/.nanobot-docker
# 构建镜像
docker build -t nanobot .

# 可选（Linux 推荐）：让容器 uid/gid 与宿主用户一致，减少挂载目录权限问题
docker build -t nanobot --build-arg NB_UID="$(id -u)" --build-arg NB_GID="$(id -g)" .

# Dockerfile 现已默认跳过 WhatsApp bridge 构建（避免外部 git 依赖失败）。
# 仅在需要 WhatsApp 渠道时显式开启：
docker build -t nanobot --build-arg BUILD_WHATSAPP_BRIDGE=1 .

# 初始化 Docker 独立配置（仅首次）
docker run -v ~/.nanobot-docker:/home/nanobot/.nanobot --rm nanobot onboard

# 在宿主机编辑 Docker 配置并填入 API Key/渠道配置
vim ~/.nanobot-docker/config.json

# 运行网关（连接 Telegram/WhatsApp）
docker run -v ~/.nanobot-docker:/home/nanobot/.nanobot -p 18790:18790 nanobot gateway

# 或执行单条命令
docker run -v ~/.nanobot-docker:/home/nanobot/.nanobot --rm nanobot agent -m "Hello!"
docker run -v ~/.nanobot-docker:/home/nanobot/.nanobot --rm nanobot status

# 网关 24/7 常驻
docker run -d --name nanobot-gateway --restart unless-stopped \
  -v ~/.nanobot-docker:/home/nanobot/.nanobot -p 18790:18790 nanobot gateway
docker logs -f nanobot-gateway

# 进入容器调试（覆盖 entrypoint）
docker run --rm --entrypoint /bin/sh \
  -v ~/.nanobot-docker:/home/nanobot/.nanobot nanobot -lc 'id && ls -la /home/nanobot/.nanobot'

# 或使用 docker compose 模板
# （默认数据目录：~/.nanobot-docker，可用 NANOBOT_DATA_DIR=/path 覆盖）
docker compose -f ops/docker-compose.gateway.yml up -d
docker compose -f ops/docker-compose.gateway.yml logs -f
```

## 📁 项目结构

```
nanobot/
├── agent/          # 🧠 Agent 核心逻辑
│   ├── loop.py     #    Agent 主循环（LLM ↔ 工具执行）
│   ├── context.py  #    Prompt 构建
│   ├── memory.py   #    持久化记忆
│   ├── skills.py   #    Skills 加载
│   ├── subagent.py #    后台任务执行
│   └── tools/      #    内置工具（含 spawn）
├── skills/         # 🎯 内置技能包（github、weather、tmux...）
├── channels/       # 📱 WhatsApp 集成
├── bus/            # 🚌 消息路由
├── cron/           # ⏰ 定时任务
├── heartbeat/      # 💓 主动唤醒
├── providers/      # 🤖 LLM Providers（OpenRouter 等）
├── session/        # 💬 会话管理
├── config/         # ⚙️ 配置
└── cli/            # 🖥️ 命令行
```

## 🤝 贡献与路线图

欢迎 PR！代码库刻意保持小而清晰，便于阅读和参与。🤗

**路线图**：选择一个条目并[提交 PR](https://github.com/HKUDS/nanobot/pulls)！

- [x] **语音转写** - 支持 Groq Whisper（Issue #13）
- [ ] **多模态** - 看见和听见（图像、语音、视频）
- [ ] **长期记忆** - 记住关键上下文
- [ ] **更强推理** - 多步规划与反思
- [ ] **更多集成** - Discord、Slack、邮件、日历
- [ ] **自我改进** - 从反馈与错误中学习

### 贡献者

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12" />
</a>


## ⭐ Star 历史

<div align="center">
  <a href="https://star-history.com/#HKUDS/nanobot&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em> 感谢访问 ✨ nanobot！</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.nanobot&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>nanobot 仅用于教育、研究与技术交流目的</sub>
</p>
