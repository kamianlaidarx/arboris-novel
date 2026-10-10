<!-- AIMETA P=章节生成对话框_写作指令|R=写作指令输入_耗时提示_确认生成|NR=不直接生成|E=component:ChapterGenerateDialog|X=internal|A=对话框|D=vue|S=dom|RD=./README.ai -->
<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    style="background-color: rgba(0,0,0,0.5);"
    @click.self="close"
  >
    <div
      class="md-card md-card-elevated w-full max-w-2xl flex flex-col"
      style="border-radius: var(--md-radius-lg);"
    >
      <div class="flex items-center justify-between px-6 py-4" style="border-bottom: 1px solid var(--md-outline-variant);">
        <div>
          <h3 class="md-title-large" style="color: var(--md-on-surface);">
            {{ isRegenerate ? '重新生成' : '生成' }}第 {{ chapterNumber }} 章
          </h3>
          <p v-if="chapterTitle" class="md-body-small mt-1" style="color: var(--md-on-surface-variant);">
            {{ chapterTitle }}
          </p>
        </div>
        <button class="md-btn md-btn-text md-ripple" @click="close">
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div>
          <label class="mb-1 block md-body-small" style="color: var(--md-on-surface-variant);">
            写作指令（可选）
          </label>
          <textarea
            v-model="notes"
            rows="4"
            placeholder="例如：多写对话少写心理；这一章要有一次反转；把节奏放慢，加强环境描写"
            class="w-full resize-y rounded-lg border px-3 py-2 text-sm outline-none"
            style="border-color: var(--md-outline-variant); background: transparent; color: var(--md-on-surface);"
          ></textarea>
          <p class="mt-1 md-body-small" style="color: var(--md-on-surface-variant);">
            留空则完全按大纲与导演脚本生成。
          </p>
        </div>

        <!-- 常用指令，点一下追加 -->
        <div class="flex flex-wrap gap-2">
          <button
            v-for="chip in chips"
            :key="chip"
            class="rounded-full px-3 py-1 text-xs md-ripple"
            style="background-color: var(--md-surface-container); color: var(--md-on-surface);"
            @click="appendChip(chip)"
          >+ {{ chip }}</button>
        </div>

        <!-- 耗时提示：一章要跑多个阶段，用户需要知道要等多久 -->
        <div
          class="rounded-lg border p-3 md-body-small"
          style="border-color: var(--md-outline-variant); background-color: var(--md-surface-container); color: var(--md-on-surface-variant);"
        >
          <p>生成一章需要多个阶段：导演脚本 → 正文 → 评审 → 事实提取 → 章间契约。</p>
          <p class="mt-1">预计耗时 <b>3–8 分钟</b>（视模型速度而定），期间可以离开页面。</p>
          <p v-if="isRegenerate" class="mt-1">重新生成会新建版本，当前内容不会被覆盖，可随时切回。</p>
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 px-6 py-4" style="border-top: 1px solid var(--md-outline-variant);">
        <button class="md-btn md-btn-text md-ripple" @click="close">取消</button>
        <button class="md-btn md-btn-filled md-ripple" @click="confirm">
          {{ isRegenerate ? '开始重新生成' : '开始生成' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  show: boolean
  chapterNumber: number
  chapterTitle?: string
  /** 已有内容时为「重新生成」，否则为「生成」 */
  isRegenerate?: boolean
}>()

const emit = defineEmits<{
  close: []
  confirm: [writingNotes: string]
}>()

const notes = ref('')

const chips = [
  '多写对话，少写心理',
  '加强冲突与张力',
  '放慢节奏，增加环境描写',
  '这一章要有一个反转',
  '减少说明性段落',
]

const appendChip = (text: string) => {
  const cur = notes.value.trim()
  notes.value = cur ? `${cur}；${text}` : text
}

const confirm = () => {
  emit('confirm', notes.value.trim())
  close()
}

const close = () => {
  emit('close')
}

// 每次打开清空，避免上一章的指令被误用到本章
watch(() => props.show, (v) => {
  if (v) notes.value = ''
})
</script>
