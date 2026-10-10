// AIMETA P=小说API客户端_小说和章节接口|R=小说CRUD_章节管理_生成|NR=不含UI逻辑|E=api:novel|X=internal|A=novelApi对象|D=axios|S=net|RD=./README.ai
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

// API 配置
// 在生产环境中使用相对路径，在开发环境中使用绝对路径
export const API_BASE_URL = import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
export const API_PREFIX = '/api'

/**
 * 解析一个 SSE 事件块（帧之间已按空行切好）。
 *
 * 形如：
 *   event: delta
 *   data: {"text":"你好"}
 *
 * 后端把 data 里的换行转义成了字面量 \n，所以这里直接 JSON.parse 即可。
 */
const parseSseEvent = (raw: string): { event: string; data: any } | null => {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}

/**
 * 调用「长任务」的流式端点，返回最终的 done 事件负载。
 *
 * 后端这类端点会周期发送注释帧（`: keep-alive`）保活，
 * 因此这里不需要处理增量文本，只要：
 *   - 持续读取，避免连接被判定为空闲
 *   - 统计已等待秒数，供界面显示「已等待 Ns」
 *   - 拿到 done 就返回，拿到 error 就抛出
 *
 * 为什么必须流式：Cloudflare 免费版对「源站 100 秒未响应」返回 524，
 * 而章节生成/蓝图生成远超这个时间。
 */
const callLongTaskStream = async <T>(
  url: string,
  body: any,
  options: { onProgress?: (seconds: number) => void } = {}
): Promise<T> => {
  const authStore = useAuthStore()
  const started = Date.now()

  const response = await fetch(`${API_BASE_URL}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authStore.token}`
    },
    body: JSON.stringify(body ?? {})
  })

  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const message = detail?.detail || `请求失败（HTTP ${response.status}）`
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: T | null = null
  let streamError: string | null = null

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''

      for (const part of parts) {
        // 注释帧（心跳）只用于保活，顺带把已等待时间报给界面
        if (part.startsWith(':')) {
          options.onProgress?.(Math.round((Date.now() - started) / 1000))
          continue
        }
        const evt = parseSseEvent(part)
        if (!evt) continue
        if (evt.event === 'done') {
          final = evt.data as T
        } else if (evt.event === 'error') {
          streamError = evt.data?.detail ?? 'AI 返回错误'
        }
      }
    }
  } finally {
    reader.releaseLock()
  }

  if (streamError) throw new Error(streamError)
  if (!final) throw new Error('AI 未返回有效内容')
  return final
}

// 统一的请求处理函数
const request = async (url: string, options: RequestInit = {}) => {
  const authStore = useAuthStore()
  const headers = new Headers({
    'Content-Type': 'application/json',
    ...options.headers
  })

  // 如果 body 是 FormData，删除 Content-Type header，让浏览器自动设置（包含 boundary）
  if (options.body instanceof FormData) {
    headers.delete('Content-Type')
  }

  if (authStore.isAuthenticated && authStore.token) {
    headers.set('Authorization', `Bearer ${authStore.token}`)
  }

  const response = await fetch(url, { ...options, headers })

  if (response.status === 401) {
    // Token 失效或未授权
    authStore.logout()
    router.push('/login')
    throw new Error('会话已过期，请重新登录')
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || `请求失败，状态码: ${response.status}`)
  }

  return response.json()
}

// 类型定义
export interface NovelProject {
  id: string
  title: string
  initial_prompt: string
  blueprint?: Blueprint
  chapters: Chapter[]
  conversation_history: ConversationMessage[]
}

export interface NovelProjectSummary {
  id: string
  title: string
  genre: string
  last_edited: string
  completed_chapters: number
  total_chapters: number
}

export interface Blueprint {
  title?: string
  target_audience?: string
  genre?: string
  style?: string
  tone?: string
  one_sentence_summary?: string
  full_synopsis?: string
  world_setting?: any
  characters?: Character[]
  relationships?: any[]
  chapter_outline?: ChapterOutline[]
}

export interface Character {
  name: string
  description: string
  identity?: string
  personality?: string
  goals?: string
  abilities?: string
  relationship_to_protagonist?: string
}

export interface ChapterOutline {
  chapter_number: number
  title: string
  summary: string
}

export interface ChapterVersion {
  content: string
  style?: string
}

export interface Chapter {
  chapter_number: number
  title: string
  summary: string
  content: string | null
  versions: string[] | null  // versions是字符串数组，不是对象数组
  evaluation: string | null
  generation_status: 'not_generated' | 'generating' | 'evaluating' | 'selecting' | 'failed' | 'evaluation_failed' | 'waiting_for_confirm' | 'successful'
  word_count?: number  // 字数统计
}

export interface ConversationMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ConverseResponse {
  ai_message: string
  ui_control: UIControl
  conversation_state: any
  is_complete: boolean
  ready_for_blueprint?: boolean  // 新增：表示准备生成蓝图
}

export interface BlueprintGenerationResponse {
  blueprint: Blueprint
  ai_message: string
}

export interface UIControl {
  type: 'single_choice' | 'text_input'
  options?: Array<{ id: string; label: string }>
  placeholder?: string
}

export interface ChapterGenerationResponse {
  versions: ChapterVersion[] // Renamed from chapter_versions for consistency
  evaluation: string | null
  ai_message: string
  chapter_number: number
}

export interface DeleteNovelsResponse {
  status: string
  message: string
}

// 内容型Section（对应后端NovelSectionType枚举）
export type NovelSectionType = 'overview' | 'world_setting' | 'characters' | 'relationships' | 'chapter_outline' | 'chapters'

// 分析型Section（不属于NovelSectionType，使用独立的analytics API）
export type AnalysisSectionType = 'emotion_curve' | 'foreshadowing'

// 所有Section的联合类型
export type AllSectionType = NovelSectionType | AnalysisSectionType

export interface NovelSectionResponse {
  section: NovelSectionType
  data: Record<string, any>
}

// API 函数
const NOVELS_BASE = `${API_BASE_URL}${API_PREFIX}/novels`
const WRITER_PREFIX = '/api/writer'
const WRITER_BASE = `${API_BASE_URL}${WRITER_PREFIX}/novels`

export class NovelAPI {
  static async createNovel(title: string, initialPrompt: string): Promise<NovelProject> {
    return request(NOVELS_BASE, {
      method: 'POST',
      body: JSON.stringify({ title, initial_prompt: initialPrompt })
    })
  }

  static async importNovel(file: File): Promise<{ id: string }> {
    const formData = new FormData()
    formData.append('file', file)
    return request(`${NOVELS_BASE}/import`, {
      method: 'POST',
      body: formData,
      headers: {
        // 让 browser 自动设置 Content-Type 为 multipart/form-data，不手动设置
      }
    })
  }

  static async getNovel(projectId: string): Promise<NovelProject> {
    return request(`${NOVELS_BASE}/${projectId}`)
  }

  static async getChapter(projectId: string, chapterNumber: number): Promise<Chapter> {
    return request(`${NOVELS_BASE}/${projectId}/chapters/${chapterNumber}`)
  }

  static async getSection(projectId: string, section: NovelSectionType): Promise<NovelSectionResponse> {
    return request(`${NOVELS_BASE}/${projectId}/sections/${section}`)
  }

  static async converseConcept(
    projectId: string,
    userInput: any,
    conversationState: any = {}
  ): Promise<ConverseResponse> {
    const formattedUserInput = userInput || { id: null, value: null }
    return request(`${NOVELS_BASE}/${projectId}/concept/converse`, {
      method: 'POST',
      body: JSON.stringify({
        user_input: formattedUserInput,
        conversation_state: conversationState
      })
    })
  }

  /**
   * 概念对话的流式版本（SSE）。
   *
   * 为什么不直接用 EventSource：它只支持 GET，而这里需要 POST 请求体
   * （user_input / conversation_state / model）。所以用 fetch + 手动解析 SSE。
   *
   * 好处是链接不会长时间静默：首字节 1~2 秒内到达，
   * 反向代理（如 Cloudflare 免费版的 100 秒静默限制）就不会掐断长生成。
   */
  static async converseConceptStream(
    projectId: string,
    userInput: any,
    conversationState: any = {},
    options: { model?: string; onDelta?: (text: string) => void; signal?: AbortSignal } = {}
  ): Promise<ConverseResponse> {
    const authStore = useAuthStore()
    const formattedUserInput = userInput || { id: null, value: null }

    const response = await fetch(`${API_BASE_URL}${NOVELS_BASE}/${projectId}/concept/converse-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authStore.token}`
      },
      body: JSON.stringify({
        user_input: formattedUserInput,
        conversation_state: conversationState,
        model: options.model ?? null
      }),
      signal: options.signal
    })

    if (!response.ok) {
      // 请求还没进入 SSE 就在网关/FastAPI 层失败（鉴权、404 等）
      const detail = await response.json().catch(() => null)
      const message = detail?.detail || `请求失败（HTTP ${response.status}）`
      throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
    }
    if (!response.body) {
      throw new Error('浏览器不支持流式响应')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let final: ConverseResponse | null = null
    let streamError: string | null = null

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE 以空行分隔事件；保留最后一段不完整的数据等下一批
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const evt = parseSseEvent(part)
          if (!evt) continue
          if (evt.event === 'delta') {
            options.onDelta?.(evt.data?.text ?? '')
          } else if (evt.event === 'done') {
            final = evt.data as ConverseResponse
          } else if (evt.event === 'error') {
            streamError = evt.data?.detail ?? 'AI 返回错误'
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    // 后端把上游错误（模型不存在、余额不足、超时…）也作为事件下发，
    // 因为此时响应头已发出，无法再改 HTTP 状态码。
    if (streamError) throw new Error(streamError)
    if (!final) throw new Error('AI 未返回有效内容')
    return final
  }

  static async generateBlueprint(
    projectId: string,
    options: { onProgress?: (seconds: number) => void } = {}
  ): Promise<BlueprintGenerationResponse> {
    // 走流式端点：蓝图实测要 160 秒，非流式会被 Cloudflare 以 524 掐断。
    return callLongTaskStream(
      `${NOVELS_BASE}/${projectId}/blueprint/generate-stream`,
      {},
      options
    )
  }

  static async saveBlueprint(projectId: string, blueprint: Blueprint): Promise<NovelProject> {
    return request(`${NOVELS_BASE}/${projectId}/blueprint/save`, {
      method: 'POST',
      body: JSON.stringify(blueprint)
    })
  }

  static async generateChapter(
    projectId: string,
    chapterNumber: number,
    options: { onProgress?: (seconds: number) => void } = {}
  ): Promise<NovelProject> {
    // 章节生成是最重的操作（多阶段 LLM 调用），必须走流式。
    return callLongTaskStream(
      `${WRITER_BASE}/${projectId}/chapters/generate-stream`,
      { chapter_number: chapterNumber },
      options
    )
  }

  static async evaluateChapter(
    projectId: string,
    chapterNumber: number,
    options: { onProgress?: (seconds: number) => void } = {}
  ): Promise<NovelProject> {
    return callLongTaskStream(
      `${WRITER_BASE}/${projectId}/chapters/evaluate-stream`,
      { chapter_number: chapterNumber },
      options
    )
  }

  static async selectChapterVersion(
    projectId: string,
    chapterNumber: number,
    versionIndex: number
  ): Promise<NovelProject> {
    return request(`${WRITER_BASE}/${projectId}/chapters/select`, {
      method: 'POST',
      body: JSON.stringify({
        chapter_number: chapterNumber,
        version_index: versionIndex
      })
    })
  }

  static async getAllNovels(): Promise<NovelProjectSummary[]> {
    return request(NOVELS_BASE)
  }

  static async deleteNovels(projectIds: string[]): Promise<DeleteNovelsResponse> {
    return request(NOVELS_BASE, {
      method: 'DELETE',
      body: JSON.stringify(projectIds)
    })
  }

  static async updateChapterOutline(
    projectId: string,
    chapterOutline: ChapterOutline
  ): Promise<NovelProject> {
    return request(`${WRITER_BASE}/${projectId}/chapters/update-outline`, {
      method: 'POST',
      body: JSON.stringify(chapterOutline)
    })
  }

  static async deleteChapter(
    projectId: string,
    chapterNumbers: number[]
  ): Promise<NovelProject> {
    return request(`${WRITER_BASE}/${projectId}/chapters/delete`, {
      method: 'POST',
      body: JSON.stringify({ chapter_numbers: chapterNumbers })
    })
  }

  static async generateChapterOutline(
    projectId: string,
    startChapter: number,
    numChapters: number
  ): Promise<NovelProject> {
    return callLongTaskStream(
      `${WRITER_BASE}/${projectId}/chapters/outline-stream`,
      {
        start_chapter: startChapter,
        num_chapters: numChapters
      }
    )
  }

  static async updateBlueprint(projectId: string, data: Record<string, any>): Promise<NovelProject> {
    return request(`${NOVELS_BASE}/${projectId}/blueprint`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    })
  }

  static async editChapterContent(
    projectId: string,
    chapterNumber: number,
    content: string
  ): Promise<Chapter> {
    return request(`${WRITER_BASE}/${projectId}/chapters/edit-fast`, {
      method: 'POST',
      body: JSON.stringify({
        chapter_number: chapterNumber,
        content: content
      })
    })
  }
}


// 优化相关类型定义
export interface EmotionBeat {
  primary_emotion: string
  intensity: number
  curve: {
    start: number
    peak: number
    end: number
  }
  turning_point: string
}

export interface OptimizeRequest {
  project_id: string
  chapter_number: number
  dimension: 'dialogue' | 'environment' | 'psychology' | 'rhythm'
  additional_notes?: string
}

export interface OptimizeResponse {
  optimized_content: string
  optimization_notes: string
  dimension: string
}

// 优化API
const OPTIMIZER_BASE = `${API_BASE_URL}${API_PREFIX}/optimizer`

export class OptimizerAPI {
  /**
   * 对章节内容进行分层优化
   */
  static async optimizeChapter(optimizeReq: OptimizeRequest): Promise<OptimizeResponse> {
    // 分层优化逐维度调用模型，总耗时长，走流式避免被代理掐断。
    // 注意 OPTIMIZER_BASE 已含 API_BASE_URL，这里要传相对路径。
    return callLongTaskStream(
      `${API_PREFIX}/optimizer/optimize-stream`,
      optimizeReq
    )
  }

  /**
   * 应用优化后的内容到章节
   */
  static async applyOptimization(
    projectId: string,
    chapterNumber: number,
    optimizedContent: string
  ): Promise<{ status: string; message: string }> {
    const params = new URLSearchParams({
      project_id: projectId,
      chapter_number: chapterNumber.toString(),
      optimized_content: optimizedContent
    })
    return request(`${OPTIMIZER_BASE}/apply-optimization?${params}`, {
      method: 'POST'
    })
  }
}
