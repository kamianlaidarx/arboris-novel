# 第三方大模型列表自动获取

本文档说明 Arboris 如何自动发现第三方服务可用的模型列表，以及这次重构改了什么、为什么这样改。

## 一、这个能力解决什么问题

用户在「个人设置 → LLM 配置」里填了自己的 API 地址与 Key 之后，不应该再去翻文档
手敲模型名——服务端应该能直接问出「你这个 Key 能看到哪些模型」。

## 二、重构前后的差异

| 维度 | 重构前 | 重构后 |
|------|--------|--------|
| 供应商识别 | `if "deepseek" in host` 一长串硬编码关键字猜测 | 数据驱动的规则表 `catalog.py`，新增供应商只需加一条记录 |
| 不支持的协议 | Anthropic / Azure / Cohere 直接返回**写死的模型清单**（会随官方更新而过期） | Anthropic 走官方 `/v1/models` 真实探测；确实无列表接口的（Azure 等）返回明确提示，不伪造清单 |
| 端点路径 | 只按 `base_url + "/models"` 拼一次，填错前缀就失败 | 按候选列表依次探测（`/models`、`/v1/models`…），命中后回报真实端点 |
| 失败处理 | 所有异常被 `except` 吞掉，统一 `return []`；前端只能弹「未获取到模型列表」 | 分级异常 + 结构化错误体（原因 / 建议 / 已尝试端点 / 上游状态码） |
| 缓存 | 无，每次点击都打第三方接口 | 进程内 TTL 缓存，按用户+供应商+地址+Key 摘要隔离，并发请求自动合并 |
| 返回内容 | `List[str]` 模型名 | 结构化 `ModelListResponse`：模型名 + 能力标签 + 命中端点 + 耗时 + 缓存状态 |
| 地址容错 | `HttpUrl` 校验，`api.deepseek.com` 这类写法直接被拒 | 自动补协议、去尾斜杠；`#` 结尾表示固定端点 |
| 安全 | 无内网限制；Google 的 Key 拼在 URL 里（会进日志） | 默认拦截内网地址（可开关）；Google Key 改走请求头 |

## 三、目录结构

```
backend/app/llm_discovery/
├── __init__.py         # 对外导出
├── models.py           # ModelInfo / ModelListResult / Capability（与传输无关）
├── errors.py           # 分级异常，自带中文 message + hint + 建议 HTTP 状态码
├── catalog.py          # 供应商目录、识别规则、地址归一化、内网判定
├── cache.py            # TTL 缓存 + 同键并发合并（asyncio.Task 去重）
├── service.py          # 编排：识别 → 拦截 → 探测 → 分类 → 限流 → 过滤 → 缓存
└── adapters/
    ├── base.py              # 客户端构造、状态码映射、能力分类启发式
    ├── openai_compatible.py # 主路径：OpenAI 兼容协议（含候选端点回退）
    ├── anthropic.py         # Claude 官方 /v1/models
    ├── google.py            # Gemini /v1beta/models
    └── ollama.py            # 本地 /api/tags
```

## 四、端点探测策略

用户填写的地址形态千差万别，因此不猜一次，而是生成一小组候选端点逐个探测：

| 用户填写的地址 | 候选端点（按顺序） |
|----------------|--------------------|
| `https://api.siliconflow.cn/v1` | `…/v1/models` |
| `https://open.bigmodel.cn/api/paas/v4` | `…/v4/models` |
| `https://api.deepseek.com` | `…/v1/models` → `…/models` |
| `https://host/openai` | `…/openai/models` → `…/openai/v1/models` |
| `https://host/v1/models` | 原样使用 |
| `https://host/custom/list#` | 原样使用（`#` = 固定端点，不做任何补全） |

规则要点：末段已是版本号（`v1`/`v4`）时只补 `/models`，**不会**拼出 `/v1/v1/models`
这种无效路径（有回归测试覆盖）。一旦某个候选返回了模型，就停止并记录该端点为
响应中的 `endpoint`——用户因此能确认真实请求打到了哪里。

## 五、错误分级

| 异常 | 触发条件 | HTTP | 给用户的建议 |
|------|----------|------|--------------|
| `InvalidCredentialsError` | 未提供 API Key | 400 | 先填 Key，或先保存配置 |
| `InvalidProviderURLError` | 地址非法（如 `ftp://`） | 400 | 需要 `http(s)://` 开头 |
| `ProviderAuthError` | 上游 401/403 | 401 | 检查 Key 是否过期、是否有该接口权限 |
| `NoModelListEndpointError` | 所有候选都 404 / 该协议无列表接口 | 404 | 属正常情况，手动输入模型名即可 |
| `ProviderRateLimitError` | 上游 429 | 429 | 稍后重试，检查额度 |
| `ProviderServerError` | 上游 5xx | 502 | 对方临时故障 |
| `ProviderUnreachableError` | 连接失败/超时 | 504 | 检查地址、网络、反代 |
| `LocalEndpointBlockedError` | 内网地址且未开开关 | 403 | 让管理员开 `ALLOW_PRIVATE_LLM_ENDPOINTS` |

响应示例（HTTP 404）：

```json
{
  "detail": {
    "error": "NoModelListEndpointError",
    "message": "该服务未提供模型列表接口",
    "hint": "这属于正常情况：请手动输入模型名称（例如 deepseek-chat、gpt-4o-mini）。",
    "provider": "openai-compatible",
    "attempted_endpoints": [
      "https://relay.example.com/v1/models",
      "https://relay.example.com/models"
    ],
    "upstream_status": 404
  }
}
```

> 内部未预期异常的原文**不会**放进响应体（可能含路径、连接串等敏感信息），只写服务端日志。

## 六、能力标签

`classify_model()` 按模型名推断标签，仅用于界面分组/筛选，不构成能力担保：

- **非对话类**：`embedding`、`rerank`、`image`、`audio`、`moderation`
- **对话类**：`reasoning`、`code`、`vision` 本身就是对话模型，会**同时**带 `chat`
- **识别不出任何特征**：按对话模型处理，标记 `chat` + `other`
  （OpenAI 兼容网关上绝大多数模型都是对话模型，用户仍应能选中）

标签上限 4 个，避免噪声。经 `parse_model_payload` 解析后按 ID 去重排序。

## 七、缓存

- 键 = `user_id | provider | base_url | sha256(api_key)[:12] | capabilities`。
  **Key 只以摘要参与**，明文不入键、不落盘、不打日志。
- 默认 TTL 300 秒（`LLM_MODEL_CACHE_TTL`），LRU 上限 128 条。
- 同一用户连点「获取模型」时，只有第一个请求真正打上游，其余共享同一个
  `asyncio.Task` 的结果（并发合并）。
- 请求体带 `refresh: true` 则先失效该键再重新探测（界面上的「强制刷新」）。
- 删除用户配置时同步清空该用户的缓存条目。

## 八、接口契约

### `POST /api/llm-config/models`

请求：

```json
{
  "llm_provider_url": "https://api.siliconflow.cn/v1",
  "llm_provider_api_key": "sk-xxx",
  "provider": null,
  "refresh": false,
  "capabilities": ["chat"]
}
```

- `llm_provider_api_key` 可省略：此时回退到该用户**已保存的配置**，因此保存后刷新无需重复粘贴 Key。
- `provider` 可显式指定（`deepseek`、`siliconflow`…），留空则按地址自动识别。
- `capabilities` 只保留包含指定能力标签的模型。

成功响应（200）：

```json
{
  "provider": "siliconflow",
  "provider_label": "SiliconFlow 硅基流动",
  "base_url": "https://api.siliconflow.cn/v1",
  "endpoint": "https://api.siliconflow.cn/v1/models",
  "models": [
    { "id": "deepseek-ai/DeepSeek-V3", "capabilities": ["chat"], "owned_by": "siliconflow" },
    { "id": "BAAI/bge-m3", "capabilities": ["embedding"], "owned_by": "siliconflow" }
  ],
  "model_ids": ["BAAI/bge-m3", "deepseek-ai/DeepSeek-V3"],
  "total": 2,
  "cached": false,
  "expires_in": 300,
  "truncated": false,
  "elapsed_ms": 412,
  "latency_ms": 412,
  "attempts": ["https://api.siliconflow.cn/v1/models"],
  "warnings": [],
  "capability_counts": { "chat": 1, "embedding": 1 }
}
```

`model_ids` 是为只关心模型名的调用方保留的扁平视图。

### 其他接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/llm-config` | 读取当前用户配置（未设置返回 404） |
| `PUT` | `/api/llm-config` | 保存配置（地址会自动归一化） |
| `DELETE` | `/api/llm-config` | 删除配置并清理该用户缓存 |
| `GET` | `/api/llm-config/providers` | 内置供应商预设（17 个），含默认地址与文档链接 |
| `GET` | `/api/llm-config/provider?base_url=…` | 识别该地址属于哪个供应商 |

`supports_model_list: false` 的预设（如 Azure OpenAI）表示该协议没有标准列表接口，
界面会提示手动输入模型名。

## 九、配置项

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `LLM_MODEL_CACHE_TTL` | `300` | 缓存秒数，`0` 关闭 |
| `LLM_MODEL_CACHE_MAX_ENTRIES` | `128` | 缓存条目上限 |
| `LLM_MODEL_REQUEST_TIMEOUT` | `15` | 单次请求超时（秒） |
| `LLM_MODEL_MAX_RESULTS` | `2000` | 单次返回模型数上限，`0` 不限 |
| `LLM_MODEL_VERIFY_TLS` | `true` | 是否校验第三方 TLS 证书 |
| `ALLOW_PRIVATE_LLM_ENDPOINTS` | `false` | 允许内网/回环地址（Ollama、自建网关需开启） |

## 十、扩展新供应商

在 `catalog.py` 的 `_DESCRIPTORS` 中追加一条即可，探测逻辑无需改动：

```python
ProviderDescriptor(
    id="my-provider",
    label="我的供应商",
    kind=ProviderKind.OPENAI_COMPATIBLE,   # 或 ANTHROPIC / GOOGLE / OLLAMA
    default_base_url="https://api.my-provider.com/v1",
    host_fragments=("api.my-provider.com",),
    docs_url="https://docs.my-provider.com/",
),
```

若它是新协议族，则需在 `adapters/` 下按 `ModelListAdapter` 协议实现 `fetch()`，
并在 `service.py` 的 `_ADAPTERS` 中注册。

## 十一、测试

```bash
cd backend

# 单元 + 集成 + API 测试（离线，用 httpx.MockTransport 拦截）
../.venv/bin/python -m pytest tests/

# 端到端：起一个模拟第三方服务 + 真实后端，走完整 HTTP 流程
../.venv/bin/python tests/e2e_model_discovery.py
```

测试覆盖的关键行为：候选端点回退、`/v1/v1` 回归、Key 不泄漏、各状态码分级、
缓存命中/刷新/用户隔离/并发合并、能力过滤与分类、内网拦截开关、
配置回退、结构化错误体、未预期异常不外泄。
