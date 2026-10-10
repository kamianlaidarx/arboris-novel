<!-- AIMETA P=蓝图过期提示_一致性报告|R=过期标记展示_可疑名字列表|NR=不修改任何内容|E=component:BlueprintStalenessBanner|X=internal|A=提示组件|D=vue|S=dom|RD=./README.ai -->
<template>
  <!-- 没有过期也没有可疑名字时完全不渲染，避免占据版面 -->
  <div v-if="showBanner" class="mb-4 space-y-2">
    <!-- 过期提示 -->
    <div
      v-if="staleness?.has_stale"
      class="rounded-xl border p-4"
      style="border-color: var(--md-outline-variant); background-color: var(--md-surface-container);"
    >
      <div class="flex items-start gap-3">
        <span class="mt-0.5 text-lg" aria-hidden="true">⚠️</span>
        <div class="min-w-0 flex-1">
          <p class="md-title-small" style="color: var(--md-on-surface);">
            蓝图已修改，部分内容基于旧版生成
          </p>
          <p class="mt-1 md-body-small" style="color: var(--md-on-surface-variant);">
            <template v-if="staleness.stale_outline_count">
              {{ staleness.stale_outline_count }} 条章节大纲
            </template>
            <template v-if="staleness.stale_outline_count && staleness.stale_chapter_count">、</template>
            <template v-if="staleness.stale_chapter_count">
              {{ staleness.stale_chapter_count }} 章正文
            </template>
            仍使用旧蓝图。系统不会自动改动它们——需要你确认后手动处理。
          </p>

          <!-- 折叠的明细 -->
          <button
            v-if="!expanded"
            class="mt-2 md-btn md-btn-text md-ripple"
            @click="expanded = true"
          >
            查看详情
          </button>
          <div v-else class="mt-3 space-y-1 md-body-small" style="color: var(--md-on-surface-variant);">
            <p v-if="staleness.stale_outline_chapters.length">
              <span class="font-medium">过期大纲章节：</span>
              {{ formatRanges(staleness.stale_outline_chapters) }}
            </p>
            <p v-if="staleness.stale_chapter_numbers.length">
              <span class="font-medium">过期正文章节：</span>
              {{ formatRanges(staleness.stale_chapter_numbers) }}
            </p>
            <!-- 历史数据没有版本号，明确区分，避免用户误以为系统漏报 -->
            <p v-if="staleness.unknown_outline_chapters.length || staleness.unknown_chapter_numbers.length" class="opacity-70">
              另有 {{ staleness.unknown_outline_chapters.length + staleness.unknown_chapter_numbers.length }} 项
              生成于版本追踪功能上线之前，无法判断是否过期。
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- 可疑名字 -->
    <div
      v-if="unknownNames.length"
      class="rounded-xl border p-4"
      style="border-color: var(--md-outline-variant); background-color: var(--md-surface-container);"
    >
      <div class="flex items-start gap-3">
        <span class="mt-0.5 text-lg" aria-hidden="true">🔍</span>
        <div class="min-w-0 flex-1">
          <p class="md-title-small" style="color: var(--md-on-surface);">
            发现 {{ unknownNames.length }} 个不在当前蓝图中的名字
          </p>
          <p class="mt-1 md-body-small" style="color: var(--md-on-surface-variant);">
            可能是改名前的旧名字。系统不会自动替换——名字相近时无法判断是笔误还是不同角色。
          </p>

          <ul class="mt-3 space-y-2">
            <li
              v-for="item in visibleNames"
              :key="item.name"
              class="flex flex-wrap items-baseline gap-x-3 gap-y-1 md-body-small"
            >
              <span class="font-medium" style="color: var(--md-on-surface);">{{ item.name }}</span>
              <span style="color: var(--md-on-surface-variant);">
                <template v-if="item.outline_count">大纲 {{ item.outline_count }} 处</template>
                <template v-if="item.outline_count && item.chapter_count"> · </template>
                <template v-if="item.chapter_count">正文 {{ item.chapter_count }} 处</template>
              </span>
              <span v-if="item.outline_chapters.length" class="opacity-60">
                章节 {{ formatRanges(item.outline_chapters) }}
              </span>
              <!-- 逐条忽略：扫描有少量误报，必须能标记「这个不用管」 -->
              <button
                class="md-btn md-btn-text md-ripple !px-2 !py-0 text-xs"
                :disabled="ignoring"
                @click="ignoreOne(item.name)"
              >忽略</button>
            </li>
          </ul>

          <div class="mt-3 flex flex-wrap items-center gap-2">
            <button
              v-if="unknownNames.length > visibleCount && !showAll"
              class="md-btn md-btn-text md-ripple"
              @click="showAll = true"
            >
              显示全部 {{ unknownNames.length }} 个
            </button>
            <!-- 一键忽略全部：用于关掉整个对比提示 -->
            <button
              class="md-btn md-btn-outlined md-ripple"
              :disabled="ignoring"
              @click="ignoreAll"
            >
              {{ ignoring ? '处理中…' : `全部忽略（${unknownNames.length} 个）` }}
            </button>
          </div>

          <!-- 已忽略的名字，可恢复 -->
          <p
            v-if="report?.ignored_names?.length"
            class="mt-3 md-body-small"
            style="color: var(--md-on-surface-variant);"
          >
            已忽略 {{ report.ignored_names.length }} 个名字
            <button class="md-btn md-btn-text md-ripple !px-2 !py-0 text-xs" @click="restoreAll">
              恢复全部
            </button>
          </p>

          <!-- 当前蓝图角色，方便对照判断 -->
          <p
            v-if="report?.blueprint_characters.length"
            class="mt-3 md-body-small opacity-70"
            style="color: var(--md-on-surface-variant);"
          >
            当前蓝图角色：{{ report.blueprint_characters.join('、') }}
          </p>

          <!-- 改名入口：检测只是提示，真正要改还得动手 -->
          <button
            class="mt-3 md-btn md-btn-filled md-ripple"
            @click="renameDialogOpen = true"
          >
            批量改名
          </button>
        </div>
      </div>
    </div>

    <!-- 改名对话框：预览 → 确认 → 应用 -->
    <CharacterRenameDialog
      :show="renameDialogOpen"
      :project-id="projectId"
      :suggestions="unknownNames.map((n) => n.name)"
      @close="renameDialogOpen = false"
      @applied="onRenameApplied"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NovelAPI } from '@/api/novel'
import type { BlueprintStaleness, ConsistencyReport } from '@/api/novel'
import CharacterRenameDialog from '@/components/CharacterRenameDialog.vue'
import { globalAlert } from '@/composables/useAlert'

const props = defineProps<{
  projectId: string
  /** 蓝图保存后由父组件递增，触发重新检测 */
  refreshKey?: number
}>()

const staleness = ref<BlueprintStaleness | null>(null)
const report = ref<ConsistencyReport | null>(null)
const expanded = ref(false)
const showAll = ref(false)
const renameDialogOpen = ref(false)
const ignoring = ref(false)
/** 列表默认只显示前几个：真正需要关注的通常是最靠前的（按出现次数排序） */
const visibleCount = 5

const unknownNames = computed(() => report.value?.unknown_names ?? [])
const visibleNames = computed(() =>
  showAll.value ? unknownNames.value : unknownNames.value.slice(0, visibleCount)
)

const showBanner = computed(
  () => Boolean(staleness.value?.has_stale) || unknownNames.value.length > 0
)

/** 把 [1,2,3,7,8] 压成 "1-3, 7-8"，章节号多时更易读。 */
const formatRanges = (numbers: number[]): string => {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b)
  const parts: string[] = []
  let start = sorted[0]
  let prev = sorted[0]
  for (let i = 1; i <= sorted.length; i++) {
    const cur = sorted[i]
    if (cur !== prev + 1) {
      parts.push(start === prev ? `${start}` : `${start}-${prev}`)
      start = cur
    }
    prev = cur
  }
  return parts.join('、')
}

const load = async () => {
  if (!props.projectId) return
  try {
    // 两个接口互不依赖，并发请求
    const [s, r] = await Promise.all([
      NovelAPI.getStaleness(props.projectId),
      NovelAPI.getConsistencyReport(props.projectId),
    ])
    staleness.value = s
    report.value = r
  } catch (err) {
    // 检测失败不应影响主界面：这是辅助提示，不是核心功能
    console.warn('蓝图一致性检测失败:', err)
  }
}

onMounted(load)
watch(() => [props.projectId, props.refreshKey], load)

/** 改名完成后重新检测：提示条必须反映最新状态，否则用户以为没生效。 */
const onRenameApplied = () => {
  expanded.value = false
  load()
}

/** 忽略单个名字（扫描误报时用）。 */
const ignoreOne = async (name: string) => {
  ignoring.value = true
  try {
    await NovelAPI.ignoreConsistencyNames(props.projectId, [name])
    await load()
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '忽略失败', '操作失败')
  } finally {
    ignoring.value = false
  }
}

/** 忽略全部：一键关掉整个对比提示。 */
const ignoreAll = async () => {
  if (!unknownNames.value.length) return
  ignoring.value = true
  try {
    // 传空数组 = 忽略当前所有可疑名字，由后端决定具体名单，
    // 避免前后端对「全部」的理解不一致
    await NovelAPI.ignoreConsistencyNames(props.projectId, [])
    showAll.value = false
    expanded.value = false
    await load()
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '忽略失败', '操作失败')
  } finally {
    ignoring.value = false
  }
}

/** 清空忽略名单，让所有名字重新参与检测。 */
const restoreAll = async () => {
  ignoring.value = true
  try {
    await NovelAPI.unignoreConsistencyNames(props.projectId, [])
    await load()
  } catch (err) {
    globalAlert.showError(err instanceof Error ? err.message : '恢复失败', '操作失败')
  } finally {
    ignoring.value = false
  }
}
</script>
