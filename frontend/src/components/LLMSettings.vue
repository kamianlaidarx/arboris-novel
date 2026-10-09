<!-- AIMETA P=LLM设置_模型配置与模型发现界面|R=LLM配置表单_模型列表获取|NR=不含模型调用|E=component:LLMSettings|X=internal|A=设置组件|D=vue|S=dom,net|RD=./README.ai -->
<template>
  <div class="bg-white/70 backdrop-blur-xl rounded-2xl shadow-lg p-8">
    <div class="flex flex-wrap items-start justify-between gap-3 mb-2">
      <h2 class="text-2xl font-bold text-gray-800">LLM 配置</h2>
      <a
        v-if="matchedPreset?.docs_url"
        :href="matchedPreset.docs_url"
        target="_blank"
        rel="noopener noreferrer"
        class="text-sm text-indigo-600 hover:text-indigo-800 underline"
      >
        查看 {{ matchedPreset.label }} 文档
      </a>
    </div>
    <h5 class="text-base text-gray-600 mb-6">建议使用自己的中转 API 和 KEY；模型列表支持自动获取，也可手动填写</h5>

    <form @submit.prevent="handleSave" class="space-y-6">
      <!-- 供应商预设 -->
      <div>
        <label for="preset" class="block text-sm font-medium text-gray-700">快速选择服务商（可选）</label>
        <select
          id="preset"
          :value="selectedPresetId"
          @change="applyPreset(($event.target as HTMLSelectElement).value)"
          class="block w-full mt-1 px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
        >
          <option value="">— 自定义 / 手动填写地址 —</option>
          <option v-for="preset in presets" :key="preset.id" :value="preset.id">
            {{ preset.label }}{{ preset.supports_model_list ? '' : '（需手动填写模型名）' }}
          </option>
        </select>
        <p v-if="activePreset?.notes" class="mt-1 text-xs text-amber-700">{{ activePreset.notes }}</p>
      </div>

      <!-- API URL -->
      <div>
        <label for="url" class="block text-sm font-medium text-gray-700">API URL</label>
        <div class="relative mt-1">
          <input
            type="text"
            id="url"
            v-model="config.llm_provider_url"
            @blur="refreshProviderHint"
            class="block w-full px-3 py-2 pr-10 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            placeholder="https://api.example.com/v1"
          />
          <button
            type="button"
            @click="clearApiUrl"
            class="absolute inset-y-0 right-2 flex items-center px-2 text-gray-400 hover:text-gray-600"
            aria-label="清空 API URL"
          >
            <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
        <div class="mt-1 flex flex-wrap items-center gap-2 text-xs">
          <span v-if="providerHint" class="text-gray-500">
            已识别为
            <span class="font-medium text-gray-700">{{ providerHint.label }}</span>
          </span>
          <span v-if="providerHint && !providerHint.supports_model_list" class="text-amber-700">
            · 该服务不提供模型列表接口，请手动输入模型名
          </span>
          <span class="text-gray-400">缺少协议会自动补 https://；以 # 结尾表示固定此端点不再自动补全路径</span>
        </div>
      </div>

      <!-- API Key -->
      <div>
        <label for="key" class="block text-sm font-medium text-gray-700">API Key</label>
        <div class="relative mt-1">
          <input
            :type="showApiKey ? 'text' : 'password'"
            id="key"
            v-model="config.llm_provider_api_key"
            class="block w-full px-3 py-2 pr-24 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            placeholder="留空则使用默认 Key"
          />
          <button
            type="button"
            @click="clearApiKey"
            class="absolute inset-y-0 right-2 flex items-center px-2 text-gray-400 hover:text-gray-600"
            aria-label="清空 API Key"
          >
            <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
          <button
            type="button"
            @click="toggleApiKeyVisibility"
            class="absolute inset-y-0 right-10 flex items-center px-2 text-gray-400 hover:text-gray-600"
            :aria-label="showApiKey ? '隐藏 API Key' : '显示 API Key'"
          >
            <svg v-if="showApiKey" class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10 5c-4.478 0-8.268 2.943-9.542 7C1.732 16.057 5.522 19 10 19s8.268-2.943 9.542-7C18.268 7.943 14.478 5 10 5zm0 10a5 5 0 110-10 5 5 0 010 10z" fill-opacity="0.2" />
              <path d="M10 7a3 3 0 100 6 3 3 0 000-6z" />
            </svg>
            <svg v-else class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zm13.707 0a4.167 4.167 0 11-8.334 0 4.167 4.167 0 018.334 0z" clip-rule="evenodd" />
              <path d="M10 8a2 2 0 100 4 2 2 0 000-4z" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Model -->
      <div>
        <label for="model" class="block text-sm font-medium text-gray-700">Model</label>
        <div class="flex flex-wrap gap-2 mt-1">
          <div class="relative flex-1 min-w-[240px]">
            <input
              type="text"
              id="model"
              v-model="config.llm_provider_model"
              @focus="onModelFocus"
              @input="onModelInput"
              @blur="hideDropdown"
              class="block w-full px-3 py-2 pr-10 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
              placeholder="留空则使用默认模型，也可直接手动输入"
            />
            <button
              type="button"
              @click="clearApiModel"
              class="absolute inset-y-0 right-2 flex items-center px-2 text-gray-400 hover:text-gray-600"
              aria-label="清空模型名称"
            >
              <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>

            <!-- 模型下拉：能力过滤 + 搜索 -->
            <div
              v-if="showModelDropdown && availableModels.length > 0"
              class="absolute z-20 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg"
            >
              <div class="p-2 border-b border-gray-200 space-y-2">
                <input
                  v-model="modelSearch"
                  type="text"
                  placeholder="搜索模型…"
                  class="block w-full px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-indigo-500 focus:border-indigo-500"
                />
                <div class="flex flex-wrap gap-1">
                  <button
                    type="button"
                    @mousedown.prevent="activeCapability = ''"
                    :class="capabilityChipClass(activeCapability === '')"
                  >
                    全部 ({{ availableModels.length }})
                  </button>
                  <button
                    v-for="cap in availableCapabilities"
                    :key="cap"
                    type="button"
                    @mousedown.prevent="activeCapability = cap"
                    :class="capabilityChipClass(activeCapability === cap)"
                  >
                    {{ capabilityLabel(cap) }} ({{ result?.capability_counts?.[cap] ?? 0 }})
                  </button>
                </div>
              </div>
              <div class="max-h-60 overflow-auto">
                <div
                  v-for="model in filteredModels"
                  :key="model.id"
                  @mousedown.prevent="selectModel(model.id)"
                  class="px-3 py-2 cursor-pointer hover:bg-indigo-50 hover:text-indigo-600 text-sm flex items-start justify-between gap-3"
                >
                  <div class="min-w-0">
                    <div class="truncate font-mono">{{ model.id }}</div>
                    <div v-if="model.description" class="text-xs text-gray-500 truncate">{{ model.description }}</div>
                  </div>
                  <span class="shrink-0 text-xs text-gray-400">{{ modelCapabilityText(model) }}</span>
                </div>
                <div v-if="filteredModels.length === 0" class="px-3 py-2 text-sm text-gray-500">
                  无匹配的模型
                </div>
              </div>
            </div>
          </div>

          <button
            type="button"
            @click="loadModels(false)"
            :disabled="isLoadingModels"
            class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <SpinnerIcon v-if="isLoadingModels" />
            <span>{{ isLoadingModels ? '获取中…' : '获取模型' }}</span>
          </button>
          <button
            type="button"
            @click="loadModels(true)"
            :disabled="isLoadingModels"
            class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
            title="忽略缓存，重新从第三方接口拉取"
          >
            强制刷新
          </button>
        </div>

        <!-- 成功状态 -->
        <div v-if="result" class="mt-2 text-xs text-gray-500 space-y-0.5">
          <div>
            共 <span class="font-medium text-gray-700">{{ result.total }}</span> 个模型
            <span v-if="result.truncated" class="text-amber-700">（已按上限截断）</span>
            · 命中端点 <span class="font-mono">{{ result.endpoint }}</span>
            · 用时 {{ result.elapsed_ms }}ms
            <span v-if="result.cached" class="text-emerald-700">
              · 来自缓存（{{ result.expires_in }}s 后过期）
            </span>
          </div>
          <div v-if="result.warnings.length" class="text-amber-700">
            {{ result.warnings.join('；') }}
          </div>
        </div>

        <!-- 发现失败：给出原因 + 排查建议 + 已尝试的端点 -->
        <div v-if="discoveryError" class="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm">
          <div class="font-medium text-red-800">{{ discoveryError.message }}</div>
          <div class="mt-1 text-red-700">{{ discoveryError.hint }}</div>
          <details v-if="discoveryError.attempted_endpoints?.length" class="mt-2 text-xs text-red-600">
            <summary class="cursor-pointer">已尝试的端点（{{ discoveryError.attempted_endpoints.length }}）</summary>
            <ul class="mt-1 list-disc list-inside font-mono break-all">
              <li v-for="endpoint in discoveryError.attempted_endpoints" :key="endpoint">{{ endpoint }}</li>
            </ul>
          </details>
          <details v-if="discoveryError.details" class="mt-2 text-xs text-red-600">
            <summary class="cursor-pointer">第三方返回的原始信息</summary>
            <div class="mt-1 break-all">{{ discoveryError.details }}</div>
          </details>
          <button
            v-if="!isUnsupportedError"
            type="button"
            @click="loadModels(true)"
            class="mt-2 text-xs text-red-700 underline hover:text-red-900"
          >
            重试
          </button>
        </div>
      </div>

      <div class="flex justify-end space-x-4 pt-4">
        <button type="button" @click="handleDelete" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors">删除配置</button>
        <button type="submit" class="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">保存</button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  CAPABILITY_ORDER,
  ModelDiscoveryError,
  capabilityLabel,
  createOrUpdateLLMConfig,
  deleteLLMConfig,
  describeProvider,
  discoverModels,
  getLLMConfig,
  getProviderPresets,
  type DiscoveryErrorDetail,
  type LLMConfigCreate,
  type ModelInfo,
  type ModelListResult,
  type ProviderPreset,
} from '@/api/llm'
import { globalAlert } from '@/composables/useAlert'

/** 内联的加载动画（避免为一个图标引入额外依赖）。 */
const SpinnerIcon = () =>
  h(
    'svg',
    { class: 'animate-spin h-4 w-4', viewBox: '0 0 24 24', fill: 'none' },
    [
      h('circle', { class: 'opacity-25', cx: 12, cy: 12, r: 10, stroke: 'currentColor', 'stroke-width': 4 }),
      h('path', {
        class: 'opacity-75',
        fill: 'currentColor',
        d: 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z',
      }),
    ],
  )

const config = ref<LLMConfigCreate>({
  llm_provider_url: '',
  llm_provider_api_key: '',
  llm_provider_model: '',
})

const presets = ref<ProviderPreset[]>([])
const selectedPresetId = ref('')
const providerHint = ref<ProviderPreset | null>(null)

const showApiKey = ref(false)
const availableModels = ref<ModelInfo[]>([])
const result = ref<ModelListResult | null>(null)
const discoveryError = ref<DiscoveryErrorDetail | null>(null)
const isLoadingModels = ref(false)
const showModelDropdown = ref(false)
const modelSearch = ref('')
const activeCapability = ref('')

/** 当前下拉选中的预设（用于展示说明与文档链接）。 */
const activePreset = computed(() => presets.value.find((item) => item.id === selectedPresetId.value) ?? null)

/** 根据当前地址识别出的供应商预设。 */
const matchedPreset = computed(() => providerHint.value ?? activePreset.value)

/** 有可选值的能力标签，按固定顺序排列。 */
const availableCapabilities = computed(() => {
  const counts = result.value?.capability_counts ?? {}
  return CAPABILITY_ORDER.filter((cap) => (counts[cap] ?? 0) > 0)
})

/** 是否属于「该服务本来就不提供模型列表接口」——这种情况重试也没有意义。 */
const isUnsupportedError = computed(() => discoveryError.value?.error === 'NoModelListEndpointError')

/** 搜索 + 能力过滤后的模型列表。 */
const filteredModels = computed(() => {
  const keyword = modelSearch.value.trim().toLowerCase()
  const capability = activeCapability.value

  return availableModels.value.filter((model) => {
    if (keyword && !model.id.toLowerCase().includes(keyword)) {
      return false
    }
    if (capability && !model.capabilities.includes(capability)) {
      return false
    }
    return true
  })
})

const modelCapabilityText = (model: ModelInfo): string =>
  model.capabilities.map(capabilityLabel).join(' / ')

const capabilityChipClass = (active: boolean): string =>
  [
    'px-2 py-0.5 rounded-full border text-xs transition-colors',
    active
      ? 'bg-indigo-600 border-indigo-600 text-white'
      : 'bg-white border-gray-300 text-gray-600 hover:border-indigo-400 hover:text-indigo-600',
  ].join(' ')

onMounted(async () => {
  presets.value = await getProviderPresets()

  const existingConfig = await getLLMConfig()
  if (existingConfig) {
    config.value = {
      llm_provider_url: existingConfig.llm_provider_url || '',
      llm_provider_api_key: existingConfig.llm_provider_api_key || '',
      llm_provider_model: existingConfig.llm_provider_model || '',
    }
    await refreshProviderHint()
  }
})

/** 应用预设：仅在地址为空时覆盖，避免丢掉用户已填写的自定义地址。 */
const applyPreset = (presetId: string) => {
  selectedPresetId.value = presetId
  const preset = presets.value.find((item) => item.id === presetId)
  if (preset?.default_base_url) {
    config.value.llm_provider_url = preset.default_base_url
    providerHint.value = preset
  }
}

/** 询问后端当前地址对应哪个供应商。 */
const refreshProviderHint = async () => {
  if (!config.value.llm_provider_url) {
    providerHint.value = null
    return
  }
  providerHint.value = await describeProvider(config.value.llm_provider_url)
}

const handleSave = async () => {
  try {
    await createOrUpdateLLMConfig(config.value)
    await globalAlert.showSuccess('设置已保存！')
  } catch {
    await globalAlert.showError('保存失败，请稍后重试。')
  }
}

const handleDelete = async () => {
  const confirmed = await globalAlert.showConfirm('确定要删除您的自定义 LLM 配置吗？删除后将恢复为默认配置。')
  if (!confirmed) {
    return
  }
  try {
    await deleteLLMConfig()
    config.value = { llm_provider_url: '', llm_provider_api_key: '', llm_provider_model: '' }
    availableModels.value = []
    result.value = null
    discoveryError.value = null
    providerHint.value = null
    selectedPresetId.value = ''
    await globalAlert.showSuccess('配置已删除！')
  } catch {
    await globalAlert.showError('删除失败，请稍后重试。')
  }
}

const toggleApiKeyVisibility = () => {
  showApiKey.value = !showApiKey.value
}

const clearApiKey = () => {
  config.value.llm_provider_api_key = ''
}

const clearApiUrl = () => {
  config.value.llm_provider_url = ''
  providerHint.value = null
  selectedPresetId.value = ''
}

const clearApiModel = () => {
  config.value.llm_provider_model = ''
}

const onModelFocus = () => {
  showModelDropdown.value = true
}

const onModelInput = () => {
  showModelDropdown.value = true
}

/**
 * 获取模型列表。
 *
 * @param refresh 为 true 时要求后端跳过缓存重新探测。
 */
const loadModels = async (refresh: boolean) => {
  if (!config.value.llm_provider_api_key) {
    await globalAlert.showError('请先填写 API Key，或先保存配置后再获取模型列表。')
    return
  }

  isLoadingModels.value = true
  discoveryError.value = null
  showModelDropdown.value = false

  try {
    const payload = await discoverModels({
      llm_provider_api_key: config.value.llm_provider_api_key,
      llm_provider_url: config.value.llm_provider_url || undefined,
      refresh,
    })

    result.value = payload
    availableModels.value = payload.models
    modelSearch.value = ''
    activeCapability.value = ''
    providerHint.value = {
      id: payload.provider,
      label: payload.provider_label,
      kind: '',
      default_base_url: payload.base_url,
      docs_url: null,
      notes: null,
      supports_model_list: true,
    }

    if (payload.models.length > 0) {
      showModelDropdown.value = true
    } else {
      await globalAlert.showError('该服务返回了空模型列表，请手动输入模型名称。')
    }
  } catch (error) {
    if (error instanceof ModelDiscoveryError) {
      discoveryError.value = error.detail
    } else {
      discoveryError.value = {
        error: 'NetworkError',
        message: '无法请求模型列表接口',
        hint: '请检查网络连接与登录状态后重试。',
      }
    }
  } finally {
    isLoadingModels.value = false
  }
}

const selectModel = (modelId: string) => {
  config.value.llm_provider_model = modelId
  showModelDropdown.value = false
}

const hideDropdown = () => {
  // 延迟隐藏，确保下拉项的 mousedown 先被处理
  setTimeout(() => {
    showModelDropdown.value = false
  }, 200)
}
</script>
