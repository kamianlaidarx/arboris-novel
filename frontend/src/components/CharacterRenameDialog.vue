<!-- AIMETA P=角色改名对话框_预览与应用|R=映射输入_差异预览_应用替换|NR=不自动决定映射|E=component:CharacterRenameDialog|X=internal|A=对话框|D=vue|S=dom|RD=./README.ai -->
<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    style="background-color: rgba(0,0,0,0.5);"
    @click.self="close"
  >
    <div
      class="md-card md-card-elevated w-full max-w-3xl max-h-[90vh] flex flex-col"
      style="border-radius: var(--md-radius-lg);"
    >
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-6 py-4" style="border-bottom: 1px solid var(--md-outline-variant);">
        <h3 class="md-title-large" style="color: var(--md-on-surface);">批量改名</h3>
        <button class="md-btn md-btn-text md-ripple" @click="close">
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <!-- 步骤一：填映射 -->
        <div v-if="!preview">
          <p class="md-body-medium mb-3" style="color: var(--md-on-surface-variant);">
            填写「旧名字 → 新名字」。系统只做<b>全名精确替换</b>，
            不会自动处理简称（如「行舟」「陆兄」），需要的话请单独添加一条映射。
          </p>

          <div v-for="(row, i) in rows" :key="i" class="flex items-center gap-2 mb-2">
            <input
              v-model="row.old"
              type="text"
              placeholder="旧名字，如 陆行舟"
              class="flex-1 rounded-lg border px-3 py-2 text-sm outline-none"
              style="border-color: var(--md-outline-variant); background: transparent; color: var(--md-on-surface);"
            />
            <span style="color: var(--md-on-surface-variant);">→</span>
            <input
              v-model="row.new"
              type="text"
              placeholder="新名字，如 李明"
              class="flex-1 rounded-lg border px-3 py-2 text-sm outline-none"
              style="border-color: var(--md-outline-variant); background: transparent; color: var(--md-on-surface);"
            />
            <button
              v-if="rows.length > 1"
              class="md-btn md-btn-text md-ripple"
              @click="rows.splice(i, 1)"
            >×</button>
          </div>

          <button class="md-btn md-btn-text md-ripple mt-1" @click="rows.push({ old: '', new: '' })">
            + 添加一条
          </button>

          <!-- 检测到的可疑名字，点一下直接填入 -->
          <div v-if="suggestionList.length" class="mt-4">
            <p class="md-body-small mb-2" style="color: var(--md-on-surface-variant);">
              检测到这些名字不在当前蓝图中，点击填入：
            </p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="s in suggestions"
                :key="s"
                class="rounded-full px-3 py-1 text-sm md-ripple"
                style="background-color: var(--md-surface-container); color: var(--md-on-surface);"
                @click="fillSuggestion(s)"
              >{{ s }}</button>
            </div>
          </div>
        </div>

        <!-- 步骤二：预览 -->
        <div v-else>
          <!-- 被拒绝的映射 -->
          <div
            v-if="preview.rejected.length"
            class="mb-4 rounded-lg border p-3"
            style="border-color: var(--md-error); background-color: var(--md-error-container);"
          >
            <p class="md-title-small mb-1" style="color: var(--md-on-error-container);">
              以下映射无法执行
            </p>
            <ul class="md-body-small space-y-1" style="color: var(--md-on-error-container);">
              <li v-for="(r, i) in preview.rejected" :key="i">
                <b>{{ r.old }} → {{ r.new }}</b>：{{ r.reason }}
              </li>
            </ul>
          </div>

          <p v-if="preview.total_replacements" class="md-body-medium mb-3" style="color: var(--md-on-surface);">
            将替换 <b>{{ preview.total_replacements }}</b> 处：
            大纲 {{ preview.affected_outline_chapters.length }} 章、
            正文 {{ preview.affected_chapter_numbers.length }} 章
          </p>
          <p v-else class="md-body-medium mb-3" style="color: var(--md-on-surface-variant);">
            没有找到可替换的内容。
          </p>

          <!-- 逐处上下文，供人工确认 -->
          <div class="space-y-3">
            <div
              v-for="(o, i) in preview.occurrences.slice(0, 40)"
              :key="i"
              class="rounded-lg border p-3"
              style="border-color: var(--md-outline-variant);"
            >
              <p class="md-body-small mb-1" style="color: var(--md-on-surface-variant);">
                第 {{ o.chapter_number }} 章 ·
                {{ o.target === 'outline' ? '大纲' : '正文' }} ·
                {{ o.count }} 处
              </p>
              <p
                v-for="(s, j) in o.samples"
                :key="j"
                class="md-body-small"
                style="color: var(--md-on-surface); word-break: break-all;"
              >{{ s }}</p>
            </div>
            <p
              v-if="preview.occurrences.length > 40"
              class="md-body-small"
              style="color: var(--md-on-surface-variant);"
            >
              仅显示前 40 处，共 {{ preview.occurrences.length }} 处。
            </p>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="flex items-center justify-between gap-3 px-6 py-4" style="border-top: 1px solid var(--md-outline-variant);">
        <p class="md-body-small" style="color: var(--md-on-surface-variant);">
          <template v-if="!preview">下一步会先预览，不会直接修改</template>
          <template v-else>正文改动会新建版本，原稿可随时切回</template>
        </p>
        <div class="flex gap-2">
          <button v-if="preview" class="md-btn md-btn-text md-ripple" @click="preview = null">
            返回修改
          </button>
          <button
            v-if="!preview"
            class="md-btn md-btn-filled md-ripple"
            :disabled="!validMapping || loading"
            @click="doPreview"
          >
            {{ loading ? '计算中…' : '预览改动' }}
          </button>
          <button
            v-else
            class="md-btn md-btn-filled md-ripple"
            :disabled="loading || !preview.total_replacements"
            @click="doApply"
          >
            {{ loading ? '应用中…' : '确认替换' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NovelAPI } from '@/api/novel'
import type { RenamePreview } from '@/api/novel'
import { globalAlert } from '@/composables/useAlert'

const props = defineProps<{
  show: boolean
  projectId: string
  /** 检测到的可疑名字，作为填写建议 */
  suggestions?: string[]
}>()

const emit = defineEmits<{ close: []; applied: [] }>()

const rows = ref<Array<{ old: string; new: string }>>([{ old: '', new: '' }])
const preview = ref<RenamePreview | null>(null)
const loading = ref(false)

const suggestionList = computed(() => props.suggestions ?? [])

const validMapping = computed(() =>
  rows.value.some((r) => r.old.trim() && r.new.trim())
)

const buildMapping = (): Record<string, string> => {
  const mapping: Record<string, string> = {}
  for (const r of rows.value) {
    const old = r.old.trim()
    const next = r.new.trim()
    if (old && next) mapping[old] = next
  }
  return mapping
}

const fillSuggestion = (name: string) => {
  const empty = rows.value.find((r) => !r.old.trim())
  if (empty) {
    empty.old = name
  } else {
    rows.value.push({ old: name, new: '' })
  }
}

const doPreview = async () => {
  loading.value = true
  try {
    preview.value = await NovelAPI.previewCharacterRename(props.projectId, buildMapping())
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '预览失败', '预览失败')
  } finally {
    loading.value = false
  }
}

const doApply = async () => {
  loading.value = true
  try {
    const result = await NovelAPI.applyCharacterRename(props.projectId, buildMapping())
    globalAlert.showSuccess(
      `已替换 ${result.replacements} 处：大纲 ${result.outlines_updated} 章、正文 ${result.chapters_updated} 章`,
      '改名完成'
    )
    emit('applied')
    close()
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '替换失败', '替换失败')
  } finally {
    loading.value = false
  }
}

const close = () => {
  preview.value = null
  rows.value = [{ old: '', new: '' }]
  emit('close')
}

// 每次打开都重置，避免上次的输入残留造成误操作
watch(() => props.show, (v) => {
  if (v) {
    preview.value = null
    rows.value = [{ old: '', new: '' }]
  }
})
</script>
