# Arboris-Novel | 面向创作者的写作辅助工具

**[English](README-en.md)** | 中文

![GitHub stars](https://img.shields.io/github/stars/t59688/arboris-novel?style=social)
![GitHub forks](https://img.shields.io/github/forks/t59688/arboris-novel?style=social)
![GitHub issues](https://img.shields.io/github/issues/t59688/arboris-novel)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

如果你想使用命令行+编辑器的方式，可搭配使用 [novel-kit](https://github.com/t59688/novel-kit)。

写作时容易卡在「主角叫什么」「故事发生在哪」「下一章写什么」这类问题上。**Arboris** 在需要时帮你理清思路、记录设定、给出可选方向，让想法落成故事。

**在线体验：** [https://arboris.aozhiai.com](https://arboris.aozhiai.com)

<p align="center">
  <table align="center">
    <tr>
      <td align="center"><strong>交流群</strong><br/><img width="220" alt="交流群二维码" src="https://github.com/user-attachments/assets/6d4fe420-f8ae-4fe4-883d-235eb576c83b" /></td>
      <td align="center"><strong>作者公众号</strong><br/><img width="220" alt="作者公众号" src="https://picui.ogmua.cn/s1/2026/02/24/699d109e4ced2.webp" /></td>
    </tr>
  </table>
</p>

---

## 界面预览

<p align="center">
  <img width="1471" alt="主界面" src="https://github.com/user-attachments/assets/a52d0214-bc1b-4792-8a2b-267b09e47379" />
</p>
<p align="center">
  <img width="1375" alt="角色管理" src="https://github.com/user-attachments/assets/0673faad-43df-4479-83ae-cffa870199a3" />
</p>
<p align="center">
  <img width="1392" alt="大纲编辑" src="https://github.com/user-attachments/assets/b7a7af24-1689-4341-aa78-26b0d74bdddd" />
</p>
<p align="center">
  <img width="1255" alt="写作界面" src="https://github.com/user-attachments/assets/c831d746-8c1a-4ce8-aa1c-9b852da15c11" />
</p>

---

## 功能概览

### 设定管理
角色、地点、派系等设定集中记录，随时查阅，避免写到后期前后矛盾（如角色外貌、世界观规则等）。

### 大纲与故事线
零散的场景和灵感可交给 AI 梳理，生成从开头到结局的主线大纲。

### 写作辅助
状态不佳时可让 AI 先出草稿再按自己的风格修改；也可自己写开头，让 AI 续写以获取灵感。

### 多版本对比
支持一次生成多版内容，挑选最符合风格的部分，逐步让模型更贴合你的笔触。

---

## 项目初衷

目标是做一个**能记住你的世界、理解角色、随故事推进的写作伙伴**，而不是单纯的自动生成器。因此做了 Arboris 并选择开源，方便更多创作者使用。

---

## 快速开始

### 方式一：Docker 部署

```bash
# 1. 复制配置文件
cp .env.example .env

# 2. 编辑 .env 中的必填项：
#    - SECRET_KEY: 随机字符串，用于 JWT 等
#    - OPENAI_API_KEY: 大模型 API Key
#    - ADMIN_DEFAULT_PASSWORD: 管理员密码（勿用默认值）

# 3. 启动（默认 SQLite，无需单独安装数据库）
docker compose up -d

# 启动后在浏览器访问 http://localhost:<端口>
```

### 方式二：使用 MySQL（Compose 内 MySQL）

```bash
# .env 中设置 DB_PROVIDER=mysql，然后执行：
DB_PROVIDER=mysql docker compose --profile mysql up -d
```

### 方式三：使用自有 MySQL

```bash
# 在 .env 中配置数据库地址、用户名、密码后执行：
DB_PROVIDER=mysql docker compose up -d
```

---

## 环境变量说明

常用配置如下（完整项见 `.env.example`）：

| 配置项 | 必填吗 | 说明 |
|--------|--------|------|
| `SECRET_KEY` | ✅ | JWT 加密密钥，需自行随机生成并妥善保管 |
| `OPENAI_API_KEY` | ✅ | 你的 LLM API Key（OpenAI 或兼容的） |
| `OPENAI_API_BASE_URL` | ❌ | API 地址，默认是 OpenAI 官方的 |
| `OPENAI_MODEL_NAME` | ❌ | 模型名称，默认 `gpt-3.5-turbo` |
| `ADMIN_DEFAULT_PASSWORD` | ❌ | 管理员初始密码，部署后务必修改 |
| `ALLOW_USER_REGISTRATION` | ❌ | 是否开放注册，默认 `false` |
| `SMTP_SERVER` / `SMTP_USERNAME` | 开放注册时必填 | 邮件服务，用于发送验证码 |
| `LLM_MODEL_CACHE_TTL` | ❌ | 模型列表缓存秒数，默认 `300`；设为 `0` 关闭缓存 |
| `LLM_MODEL_REQUEST_TIMEOUT` | ❌ | 获取模型列表的单次请求超时，默认 `15` 秒 |
| `ALLOW_PRIVATE_LLM_ENDPOINTS` | ❌ | 是否允许 LLM 地址指向内网（Ollama、自建网关需开启），默认 `false` |

> **数据存储：** 默认 SQLite，数据在 Docker 卷中。需映射到本地时，在 `.env` 中设置 `SQLITE_STORAGE_SOURCE=./storage`。

---

## 自动获取第三方大模型列表

在「个人设置 → LLM 配置」中填写 API URL 与 API Key 后，点击 **获取模型** 即可自动拉取该服务
支持的模型列表（也可手动输入任意模型名）。实现细节见 [模型发现文档](docs/model_discovery.md)。

**支持的协议**

| 协议 | 覆盖服务 |
|------|----------|
| OpenAI 兼容 `/v1/models` | OpenAI、DeepSeek、Moonshot、SiliconFlow、OpenRouter、Groq、Mistral、xAI、Together、阿里云百炼，以及各类第三方中转站与自建网关 |
| Anthropic | Claude 官方 `/v1/models`（使用 `x-api-key` 头） |
| Google Gemini | `/v1beta/models`，自动过滤不可生成的模型 |
| Ollama | 本地 `/api/tags`（需开启 `ALLOW_PRIVATE_LLM_ENDPOINTS`） |

**几个实用细节**

- **地址不用写全**：填 `api.deepseek.com` 也会自动补成 `https://api.deepseek.com/v1`；
  程序会按候选路径依次探测，命中真实端点后会在界面上显示出来。以 `#` 结尾表示固定该端点、不再自动补全路径。
- **模型带能力标签**：返回的模型会按命名推断出「对话 / 推理 / 视觉 / 向量 / 重排 / 图像生成」等标签，
  可在下拉框中按能力筛选。这只是命名启发式，不影响你手动输入任意模型名。
- **失败会说清原因**：认证失败、限流、不提供列表接口、地址不通等情况会分别给出
  明确提示与排查建议，并列出实际尝试过的端点。

---


## 常见问题

### 基础使用

**Q: 不会用 Docker？**  
A: 安装 Docker Desktop（Windows/Mac）或 Docker Engine（Linux），按上文命令执行即可。

**Q: API Key 会泄露吗？**  
A: 不会。密钥仅存在于服务端 `.env`，不向前端或用户暴露。

**Q: 是否支持其他大模型？**  
A: 支持。只要提供 OpenAI 兼容接口，在 `.env` 中配置 `OPENAI_API_BASE_URL` 即可；
也可以在个人设置里配置自己的地址与 Key，并一键 **获取模型** 拉取可用模型列表。

**Q: 点「获取模型」提示「该服务未提供模型列表接口」？**  
A: 这通常不是故障——部分中转站与网关确实没有 `/v1/models` 端点。此时手动输入模型名即可
（例如 `deepseek-chat`、`gpt-4o-mini`）。界面上会列出实际尝试过的端点，便于确认地址是否写对。

**Q: 修改了代码如何参与？**  
A: 欢迎提交 PR 或 Issue。

### 生成小说时的常见错误

**Q: 提示"未配置默认 LLM API Key"怎么办？**  
A: 检查 `.env` 文件中的 `OPENAI_API_KEY` 是否正确配置。如果是个人用户，也可以在个人设置中配置自定义 API Key。

**Q: 生成时提示"今日请求次数已达上限"？**  
A: 系统管理员可能设置了每日请求限制。解决方案：
- 等到明天再试
- 在个人设置中配置自己的 API Key（不受系统配额限制）
- 管理员调整配额限制（修改 `daily_request_limit` 配置）

**Q: 提示"AI 服务响应超时"或"无法连接到 AI 服务"？**  
A: 网络或 API 服务问题导致。可以：
- 检查网络连接是否正常
- 确认 `OPENAI_API_BASE_URL` 配置是否正确
- 如果使用自建服务，检查服务是否正常运行
- 稍后重试

**Q: 提示"AI 响应因长度限制被截断"？**  
A: 生成的内容超过了模型的输出限制。建议：
- 使用支持更长输出的模型

**Q: 提示"AI 未返回有效内容"或"AI 服务内部错误"？**  
A: AI 服务端出现问题。通常是暂时性的，可以：
- 大多是LLM服务的问题，尤其是逆向的API。
- 检查 API Key 是否有效且有足够余额
- 查看后端日志获取详细错误信息

**Q: 提示"蓝图中未找到对应章节纲要"？**  
A: 在生成章节内容前，需要先在蓝图（大纲）中创建对应章节的纲要。请先完善章节大纲再进行生成。

**Q: 提示"未配置摘要提示词"？**  
A: 系统缺少必要的 Prompt 配置。管理员需要在后台配置名为 `extraction` 的提示词模板，用于生成章节摘要。

**Q: 提示"AI 返回的内容格式不正确"或 JSON 解析错误？**（较常见）  
A: AI 返回内容无法解析为有效 JSON。可能原因与处理方式：
- **原因 1：模型能力不足** - 某些模型难以稳定输出结构化 JSON
  - 解决：切换到能力更强的模型
  - 或使用支持 structured output 的模型
- **原因 2：内容过长** - 某些逆向API可能无法支持长输出。

- **临时处理：** 重试几次，或更换 AI 模型

**Q: 生成的内容质量不理想怎么办？**  
A: 可以尝试：
- 完善角色、地点、派系等设定信息
- 优化章节纲要，提供更详细的指引
- 使用多版本生成功能，让 AI 生成多个版本后挑选最佳的
- 调整使用的模型，需要长上下文的

---

## 技术栈

- **后端：** Python + FastAPI
- **数据库：** SQLite（默认）或 MySQL + libsql
- **前端：** Vue + TailwindCSS
- **部署：** Docker + Docker Compose
- **AI：** OpenAI API 或兼容接口

---

## 面向开发者

### 环境准备

- Python 3.10+（建议使用虚拟环境）
- Node.js 18+ 与 npm
- pip / virtualenv（或你习惯的依赖管理工具）
- 可选：Docker 与 Docker Compose（用于一键部署与发布）

### 后端本地开发

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows 使用 .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

默认会监听 `http://127.0.0.1:8000`，你可以通过 `--host`、`--port` 调整，或加上 `--reload` 保持热重载。

### 前端本地开发

```bash
cd frontend
npm install
npm run dev
```

开发服务器默认运行在 `http://127.0.0.1:5173`，可通过 `--host` 参数暴露给局域网设备。

### 打包与构建

- 前端：`npm run build`，构建产物位于 `frontend/dist/`
- 后端：确认依赖锁定后，可使用 `pip install -r requirements.txt` 安装到目标环境，或基于 `deploy/Dockerfile` 构建镜像
- 静态文件托管：生产环境下可用 Nginx 等服务托管 `dist` 目录，并由后端提供 API

### 发布与部署

推荐在根目录下使用 Compose 文件完成一体化部署：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

如需推送镜像，可在 `deploy` 目录执行 `docker build -t <registry>/arboris:<tag> .`，测试后再 `docker push` 发布。

---

## 参与贡献

- Star 项目
- 在 Issues 中反馈 Bug 或建议
- 提交 PR 贡献代码
- 通过文首二维码加入交流群

---

## 反馈与致谢

使用 Arboris 写出作品后，欢迎与我们分享。祝写作顺利。

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

[![Star History Chart](https://api.star-history.com/svg?repos=t59688/arboris-novel&type=Date)](https://star-history.com/#t59688/arboris-novel&Date)
