<!-- AIMETA P=模型切换器_全站可用的模型下拉|R=模型选择_切换_刷新列表|NR=不含业务逻辑|E=ModelSwitcher|X=internal|A=Vue组件|D=vue,llmApi|S=net|RD=./README.ai -->
<template>
  <div class="relative inline-block text-left" ref="rootEl">
    <button
      type="button"
      class="inline-flex items-center gap-2 rounded-lg border border-[#E4E1D8] bg-white px-3 py-1.5 text-sm
             text-[#4A4A4A] shadow-sm transition hover:border-[#C9C4B4] hover:bg-[#FBFAF6]
             disabled:cursor-not-allowed disabled:opacity-60"
      :disabled="loading"
      @click="toggle"
    >
      <span class="text-[#8B8578]">模型</span>
      <span class="max-w-[16rem] truncate font-medium text-[#2F2F2F]">
        {{ activeLabel || '未设置' }}
      </span>
      <svg
        class="h-3.5 w-3.5 text-[#8B8578] transition-transform"
        :class="open ? 'rotate-180' : ''"
        viewBox="0 0 20 20" fill="currentColor"
      >
        <path fill-rule="evenodd"
          d="M5.23 7.21a.75.75 0 011.06.02L10 11.06l3.71-3.83a.75.75 0 111.08 1.04l-4.25 4.39a.75.75 0 01-1.08 0L5.21 8.27a.75.75 0 01.02-1.06z"
          clip-rule="evenodd" />
      </svg>
    </button>

    <div
      v-if="open"
      class="absolute right-0 z-50 mt-1 w-72 overflow-hidden rounded-xl border border-[#E4E1D8]
             bg-white shadow-lg"
    >
      <div class="max-h-80 overflow-y-auto py-1">
        <p v-if="!models.length" class="px-3 py-3 text-sm text-[#8B8578]">
          还没有可切换的模型，点下方「添加模型」或到设置里配置。
        </p>

        <button
          v-for="m in models"
          :key="m.id"
          type="button"
          class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm
                 transition hover:bg-[#F5F3EC]"
          @click="select(m)"
        >
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[#2F2F2F]">{{ m.display_name || m.model_name }}</span>
            <span v-if="m.note" class="block truncate text-xs text-[#9A9486]">{{ m.note }}</span>
          </span>
          <svg v-if="m.is_active" class="h-4 w-4 shrink-0 text-[#6B8E5A]" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd"
              d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 111.4-1.4l3.8 3.8 6.8-6.8a1 1 0 011.4 0z"
              clip-rule="evenodd" />
          </svg>
        </button>
      </div>

      <div class="border-t border-[#EFEDE4] p-2">
        <div class="flex items-center gap-1.5">
          <input
            v-model="newModel"
            type="text"
            placeholder="输入模型名后回车"
            class="min-w-0 flex-1 rounded-md border border-[#E4E1D8] px-2 py-1.5 text-sm
                   outline-none focus:border-[#C9C4B4]"
            @keyup.enter="addAndSelect"
          />
          <button
            type="button"
            class="rounded-md bg-[#4A4A4A] px-2.5 py-1.5 text-sm text-white transition hover:bg-[#333]"
            @click="addAndSelect"
          >
            添加
          </button>
        </div>
        <button
          type="button"
          class="mt-1.5 w-full rounded-md px-2 py-1.5 text-xs text-[#6B665C] transition hover:bg-[#F5F3EC]"
          :disabled="loading"
          @click="pullFromGateway"
        >
          {{ loading ? '获取中…' : '从网关拉取可用模型' }}
        </button>
        <p v-if="error" class="mt-1 px-1 text-xs text-[#B4574B]">{{ error }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  activateMyModel,
  bulkAddMyModels,
  discoverModels,
  listMyModels,
  type UserModel,
} from '@/api/llm'

const emit = defineEmits<{ (e: 'changed', model: string): void }>()

const rootEl = ref<HTMLElement | null>(null)
const open = ref(false)
const loading = ref(false)
const error = ref('')
const models = ref<UserModel[]>([])
const activeModel = ref<string | null>(null)
const newModel = ref('')

const activeLabel = computed(
  () => models.value.find((m) => m.is_active)?.display_name
    || models.value.find((m) => m.is_active)?.model_name
    || activeModel.value
    || '',
)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await listMyModels()
    models.value = result.models
    activeModel.value = result.active_model
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载模型列表失败'
  } finally {
    loading.value = false
  }
}

const toggle = async () => {
  open.value = !open.value
  if (open.value && !models.value.length) {
    await load()
  }
}

const select = async (m: UserModel) => {
  if (m.is_active) {
    open.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await activateMyModel({ modelId: m.id })
    models.value = result.models
    activeModel.value = result.active_model
    open.value = false
    emit('changed', m.model_name)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '切换失败'
  } finally {
    loading.value = false
  }
}

const addAndSelect = async () => {
  const name = newModel.value.trim()
  if (!name) return
  loading.value = true
  error.value = ''
  try {
    // 后端在模型未收藏时会自动加入，所以这里直接切换即可
    const result = await activateMyModel({ modelName: name })
    models.value = result.models
    activeModel.value = result.active_model
    newModel.value = ''
    open.value = false
    emit('changed', name)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '添加失败'
  } finally {
    loading.value = false
  }
}

/** 从网关拉取模型列表并批量加入，方便一次性把可用模型都收进来。 */
const pullFromGateway = async () => {
  loading.value = true
  error.value = ''
  try {
    const discovered = await discoverModels({ refresh: true })
    const ids = discovered.model_ids ?? discovered.models.map((m) => m.id)
    if (!ids.length) {
      error.value = '网关没有返回任何模型'
      return
    }
    const result = await bulkAddMyModels(ids)
    models.value = result.models
    activeModel.value = result.active_model
  } catch (e) {
    error.value = e instanceof Error ? e.message : '拉取模型失败'
  } finally {
    loading.value = false
  }
}

/** 点击外部关闭下拉 */
const onDocClick = (e: MouseEvent) => {
  if (rootEl.value && !rootEl.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  load()
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
})

defineExpose({ reload: load, activeModel })
</script>
