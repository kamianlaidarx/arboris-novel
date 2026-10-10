<!-- AIMETA P=大纲重生成对话框_范围与预览|R=范围输入_建议输入_新旧对比_确认应用|NR=不自动覆盖|E=component:OutlineRegenDialog|X=internal|A=对话框|D=vue|S=dom|RD=./README.ai -->
<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    style="background-color: rgba(0,0,0,0.5);"
    @click.self="close"
  >
    <div
      class="md-card md-card-elevated w-full max-w-4xl max-h-[90vh] flex flex-col"
      style="border-radius: var(--md-radius-lg);"
    >
      <div class="flex items-center justify-between px-6 py-4" style="border-bottom: 1px solid var(--md-outline-variant);">
        <h3 class="md-title-large" style="color: var(--md-on-surface);">AI 重新生成章节大纲</h3>
        <button class="md-btn md-btn-text md-ripple" @click="close">
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <!-- 步骤一：范围与建议 -->
        <template v-if="!preview">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="mb-1 block md-body-small" style="color: var(--md-on-surface-variant);">
                起始章节
              </label>
              <input
                v-model.number="startChapter"
                type="number"
                min="1"
                class="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                style="border-color: var(--md-outline-variant); background: transparent; color: var(--md-on-surface);"
              />
            </div>
            <div>
              <label class="mb-1 block md-body-small" style="color: var(--md-on-surface-variant);">
                生成章数（上限 {{ MAX_CHAPTERS }}）
              </label>
              <input
                v-model.number="numChapters"
                type="number"
                min="1"
                :max="MAX_CHAPTERS"
                class="w-full rounded-lg border px-3 py-2 text-sm outline-none"
                style="border-color: var(--md-outline-variant); background: transparent; color: var(--md-on-surface);"
              />
            </div>
          </div>

          <!-- 快捷范围 -->
          <div class="flex flex-wrap gap-2">
            <button
              v-for="preset in presets"
              :key="preset.label"
              class="rounded-full px-3 py-1 text-xs md-ripple"
              style="background-color: var(--md-surface-container); color: var(--md-on-surface);"
              @click="applyPreset(preset)"
            >{{ preset.label }}</button>
          </div>

          <div>
            <label class="mb-1 block md-body-small" style="color: var(--md-on-surface-variant);">
              优化建议与限制（可选）
            </label>
            <textarea
              v-model="instructions"
              rows="4"
              placeholder="例如：节奏再紧凑些；每章结尾留一个悬念；不要引入新角色；第 5-8 章合并成两章"
              class="w-full resize-y rounded-lg border px-3 py-2 text-sm outline-none"
              style="border-color: var(--md-outline-variant); background: transparent; color: var(--md-on-surface);"
            ></textarea>
            <!-- 常用项，点一下追加到输入框 -->
            <div class="mt-2 flex flex-wrap gap-2">
              <button
                v-for="chip in chips"
                :key="chip"
                class="rounded-full px-3 py-1 text-xs md-ripple"
                style="background-color: var(--md-surface-container); color: var(--md-on-surface);"
                @click="appendInstruction(chip)"
              >+ {{ chip }}</button>
            </div>
          </div>

          <label class="flex items-center gap-2 md-body-small" style="color: var(--md-on-surface-variant);">
            <input v-model="keepExisting" type="checkbox" />
            参考已有大纲的情节走向（取消勾选表示可以完全重新设计）
          </label>
        </template>

        <!-- 步骤二：新旧对比 -->
        <template v-else>
          <div
            v-if="preview.warnings.length"
            class="rounded-lg border p-3"
            style="border-color: var(--md-outline-variant); background-color: var(--md-surface-container);"
          >
            <p v-for="(w, i) in preview.warnings" :key="i" class="md-body-small" style="color: var(--md-on-surface);">
              ⚠️ {{ w }}
            </p>
          </div>

          <p class="md-body-medium" style="color: var(--md-on-surface);">
            共 {{ preview.drafts.length }} 章：
            新增 {{ preview.drafts.filter(d => d.is_new).length }} 条、
            覆盖 {{ preview.overwritten_chapters.length }} 条
          </p>

          <div class="space-y-3">
            <div
              v-for="d in preview.drafts"
              :key="d.chapter_number"
              class="rounded-lg border p-3"
              style="border-color: var(--md-outline-variant);"
            >
              <div class="mb-2 flex items-center gap-2">
                <span class="md-title-small" style="color: var(--md-on-surface);">
                  第 {{ d.chapter_number }} 章
                </span>
                <span
                  class="rounded px-1.5 py-0.5 text-xs"
                  :style="d.is_new
                    ? 'background-color: var(--md-primary-container); color: var(--md-on-primary-container);'
                    : 'background-color: var(--md-surface-container); color: var(--md-on-surface-variant);'"
                >{{ d.is_new ? '新增' : '覆盖' }}</span>
                <span
                  v-if="d.has_prose"
                  class="rounded px-1.5 py-0.5 text-xs"
                  style="background-color: var(--md-error-container); color: var(--md-on-error-container);"
                >已有正文</span>
              </div>

              <!-- 旧内容（仅覆盖时显示） -->
              <div v-if="!d.is_new" class="mb-2 rounded p-2" style="background-color: var(--md-surface-container);">
                <p class="text-xs opacity-70" style="color: var(--md-on-surface-variant);">原内容</p>
                <p class="text-sm line-through opacity-70" style="color: var(--md-on-surface);">
                  {{ d.existing_title }}
                </p>
                <p class="text-xs line-through opacity-60" style="color: var(--md-on-surface);">
                  {{ (d.existing_summary || '').slice(0, 100) }}
                </p>
              </div>

              <!-- 新内容 -->
              <p class="text-sm font-medium" style="color: var(--md-on-surface);">{{ d.title }}</p>
              <p class="mt-1 text-sm" style="color: var(--md-on-surface-variant);">{{ d.summary }}</p>
            </div>
          </div>
        </template>
      </div>

      <div class="flex items-center justify-between gap-3 px-6 py-4" style="border-top: 1px solid var(--md-outline-variant);">
        <p class="md-body-small" style="color: var(--md-on-surface-variant);">
          <template v-if="!preview">生成后先预览，确认才会写入</template>
          <template v-else>确认后将覆盖 {{ preview.overwritten_chapters.length }} 条已有大纲</template>
        </p>
        <div class="flex gap-2">
          <button v-if="preview" class="md-btn md-btn-text md-ripple" @click="preview = null">
            返回修改
          </button>
          <button
            v-if="!preview"
            class="md-btn md-btn-filled md-ripple"
            :disabled="loading || !valid"
            @click="doGenerate"
          >
            {{ loading ? '生成中…（可能需要几分钟）' : '生成并预览' }}
          </button>
          <button
            v-else
            class="md-btn md-btn-filled md-ripple"
            :disabled="loading || !preview.drafts.length"
            @click="doApply"
          >
            {{ loading ? '写入中…' : '确认应用' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NovelAPI } from '@/api/novel'
import type { OutlineRegenPreview } from '@/api/novel'
import { globalAlert } from '@/composables/useAlert'

const MAX_CHAPTERS = 30

const props = defineProps<{
  show: boolean
  projectId: string
  /** 现有大纲数量，用于算默认范围 */
  existingCount?: number
}>()

const emit = defineEmits<{ close: []; applied: [] }>()

const startChapter = ref(1)
const numChapters = ref(10)
const instructions = ref('')
const keepExisting = ref(true)
const preview = ref<OutlineRegenPreview | null>(null)
const loading = ref(false)

const valid = computed(
  () => startChapter.value >= 1 && numChapters.value >= 1 && numChapters.value <= MAX_CHAPTERS
)

const presets = computed(() => {
  const total = props.existingCount ?? 0
  const list: Array<{ label: string; start: number; count: number }> = []
  if (total > 0) {
    list.push({ label: '从头重做前 10 章', start: 1, count: 10 })
    list.push({ label: `重做最后 10 章`, start: Math.max(1, total - 9), count: 10 })
    list.push({ label: `重做全部 ${total} 章`, start: 1, count: Math.min(total, MAX_CHAPTERS) })
  }
  list.push({ label: `从第 ${total + 1} 章续写 10 章`, start: total + 1, count: 10 })
  return list
})

const chips = [
  '节奏再紧凑些',
  '每章结尾留悬念',
  '不要引入新角色',
  '加强主角动机',
  '减少说明性段落',
]

const applyPreset = (p: { start: number; count: number }) => {
  startChapter.value = p.start
  numChapters.value = p.count
}

const appendInstruction = (text: string) => {
  const cur = instructions.value.trim()
  instructions.value = cur ? `${cur}；${text}` : text
}

const doGenerate = async () => {
  loading.value = true
  try {
    preview.value = await NovelAPI.regenerateOutline(props.projectId, {
      start_chapter: startChapter.value,
      num_chapters: numChapters.value,
      instructions: instructions.value,
      keep_existing: keepExisting.value,
    })
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '生成失败', '生成失败')
  } finally {
    loading.value = false
  }
}

const doApply = async () => {
  if (!preview.value) return
  loading.value = true
  try {
    const result = await NovelAPI.applyRegeneratedOutline(
      props.projectId,
      preview.value.drafts.map((d) => ({
        chapter_number: d.chapter_number,
        title: d.title,
        summary: d.summary,
      }))
    )
    globalAlert.showSuccess(
      `新增 ${result.created} 条、覆盖 ${result.updated} 条大纲`,
      '已应用'
    )
    emit('applied')
    close()
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '应用失败', '应用失败')
  } finally {
    loading.value = false
  }
}

const close = () => {
  preview.value = null
  emit('close')
}

// 打开时按现有数量给个合理默认，避免用户每次都手填
watch(() => props.show, (v) => {
  if (v) {
    preview.value = null
    startChapter.value = 1
    numChapters.value = Math.min(Math.max(props.existingCount ?? 0, 1) || 10, MAX_CHAPTERS)
  }
})
</script>
