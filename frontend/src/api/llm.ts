// AIMETA P=LLM_API客户端_模型配置与模型发现|R=LLM配置CRUD_模型发现|NR=不含UI逻辑|E=api:llm|X=internal|A=llmApi对象|D=fetch|S=net|RD=./README.ai
import { useAuthStore } from '@/stores/auth'

const API_PREFIX = '/api'
const LLM_BASE = `${API_PREFIX}/llm-config`

export interface LLMConfig {
  user_id: number
  llm_provider_url: string | null
  llm_provider_api_key: string | null
  llm_provider_model: string | null
}

export interface LLMConfigCreate {
  llm_provider_url?: string
  llm_provider_api_key?: string
  llm_provider_model?: string
}

/** 单个模型条目。capabilities 为后端按命名启发式推断的能力标签。 */
export interface ModelInfo {
  id: string
  capabilities: string[]
  owned_by?: string | null
  created?: number | null
  description?: string | null
}

/** 模型发现结果。 */
export interface ModelListResult {
  provider: string
  provider_label: string
  base_url: string | null
  /** 实际命中并返回模型列表的端点，便于用户确认真实请求地址 */
  endpoint: string | null
  models: ModelInfo[]
  /** 扁平模型名列表，方便只关心名字的调用方 */
  model_ids: string[]
  total: number
  /** 是否来自缓存 */
  cached: boolean
  /** 缓存剩余有效秒数 */
  expires_in: number
  /** 是否因数量上限被截断 */
  truncated: boolean
  elapsed_ms: number
  latency_ms: number | null
  /** 按顺序尝试过的端点 */
  attempts: string[]
  warnings: string[]
  capability_counts: Record<string, number>
}

/** 供应商预设，用于一键填充地址。 */
export interface ProviderPreset {
  id: string
  label: string
  kind: string
  default_base_url: string | null
  docs_url: string | null
  notes: string | null
  /** 为 false 表示该供应商没有标准模型列表接口，需手动输入模型名 */
  supports_model_list: boolean
}

export interface DiscoverModelsRequest {
  llm_provider_url?: string
  llm_provider_api_key?: string
  provider?: string
  /** 跳过缓存强制刷新 */
  refresh?: boolean
  /** 只返回包含指定能力标签的模型 */
  capabilities?: string[]
}

/** 后端返回的结构化错误详情。 */
export interface DiscoveryErrorDetail {
  error: string
  message: string
  hint: string
  provider?: string
  endpoint?: string
  attempted_endpoints?: string[]
  upstream_status?: number
  details?: string
}

/**
 * 模型发现失败时抛出的错误。
 *
 * 相比旧实现「失败就返回空数组」，这里保留了后端给出的
 * message / hint / attempted_endpoints，供界面直接展示可操作的排查建议。
 */
export class ModelDiscoveryError extends Error {
  readonly detail: DiscoveryErrorDetail
  readonly status: number

  constructor(status: number, detail: DiscoveryErrorDetail) {
    super(detail.message || '获取模型列表失败')
    this.name = 'ModelDiscoveryError'
    this.status = status
    this.detail = detail
  }

  /** 是否属于「该服务本来就不提供模型列表」这一正常情况。 */
  get isUnsupported(): boolean {
    return this.detail.error === 'NoModelListEndpointError'
  }
}

const getHeaders = (): Record<string, string> => {
  const authStore = useAuthStore()
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${authStore.token}`,
  }
}

/** 把后端错误响应解析成结构化错误对象。 */
const toDiscoveryError = async (response: Response): Promise<ModelDiscoveryError> => {
  let detail: DiscoveryErrorDetail = {
    error: 'UnknownError',
    message: `获取模型列表失败（HTTP ${response.status}）`,
    hint: '请检查网络连接与 API 配置后重试。',
  }
  try {
    const payload = await response.json()
    const raw = payload?.detail
    if (raw && typeof raw === 'object') {
      detail = { ...detail, ...raw }
    } else if (typeof raw === 'string' && raw) {
      detail = { ...detail, message: raw }
    }
  } catch {
    // 响应体不是 JSON：保留默认提示
  }
  return new ModelDiscoveryError(response.status, detail)
}

export const getLLMConfig = async (): Promise<LLMConfig | null> => {
  const response = await fetch(LLM_BASE, {
    method: 'GET',
    headers: getHeaders(),
  })
  if (response.status === 404) {
    return null
  }
  if (!response.ok) {
    throw new Error('Failed to fetch LLM config')
  }
  return response.json()
}

export const createOrUpdateLLMConfig = async (config: LLMConfigCreate): Promise<LLMConfig> => {
  const response = await fetch(LLM_BASE, {
    method: 'PUT',
    headers: getHeaders(),
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    throw new Error('Failed to save LLM config')
  }
  return response.json()
}

export const deleteLLMConfig = async (): Promise<void> => {
  const response = await fetch(LLM_BASE, {
    method: 'DELETE',
    headers: getHeaders(),
  })
  if (!response.ok) {
    throw new Error('Failed to delete LLM config')
  }
}

/** 获取内置供应商预设。失败时返回空数组，不影响主流程。 */
export const getProviderPresets = async (): Promise<ProviderPreset[]> => {
  try {
    const response = await fetch(`${LLM_BASE}/providers`, {
      method: 'GET',
      headers: getHeaders(),
    })
    if (!response.ok) {
      return []
    }
    return await response.json()
  } catch {
    return []
  }
}

/** 根据地址识别供应商，用于界面展示「已识别为 …」。 */
export const describeProvider = async (baseUrl?: string): Promise<ProviderPreset | null> => {
  try {
    const query = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : ''
    const response = await fetch(`${LLM_BASE}/provider${query}`, {
      method: 'GET',
      headers: getHeaders(),
    })
    if (!response.ok) {
      return null
    }
    return await response.json()
  } catch {
    return null
  }
}

/**
 * 自动获取第三方大模型的可用模型列表。
 *
 * 失败时抛出 {@link ModelDiscoveryError}，调用方应展示其 message / hint。
 */
export const discoverModels = async (request: DiscoverModelsRequest): Promise<ModelListResult> => {
  const response = await fetch(`${LLM_BASE}/models`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    throw await toDiscoveryError(response)
  }
  return response.json()
}

/** 能力标签的中文名，用于界面分组与过滤。 */
export const CAPABILITY_LABELS: Record<string, string> = {
  chat: '对话',
  reasoning: '推理',
  vision: '视觉',
  code: '代码',
  embedding: '向量',
  rerank: '重排',
  image: '图像生成',
  audio: '语音',
  moderation: '审核',
  other: '其他',
}

/** 界面过滤器的展示顺序。 */
export const CAPABILITY_ORDER = [
  'chat',
  'reasoning',
  'vision',
  'code',
  'embedding',
  'rerank',
  'image',
  'audio',
  'moderation',
  'other',
]

export const capabilityLabel = (key: string): string => CAPABILITY_LABELS[key] ?? key
