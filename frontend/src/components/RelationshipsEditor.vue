<!-- AIMETA P=关系编辑器_角色关系编辑|R=关系CRUD_角色名下拉|NR=不含角色编辑|E=component:RelationshipsEditor|X=internal|A=编辑器|D=vue|S=dom|RD=./README.ai -->
<template>
  <div class="space-y-4 max-h-96 overflow-y-auto p-1">
    <!-- 角色名不同步时的提示：关系按【名字】关联角色，改名会让旧关系指向不存在的角色 -->
    <div
      v-if="orphanNames.length"
      class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
    >
      <p class="font-medium">以下名字在「主要角色」里找不到：</p>
      <p class="mt-1">{{ orphanNames.join('、') }}</p>
      <p class="mt-1 text-amber-700">
        可能是角色改名或删除过。请从下拉里重新选择，否则这条关系不会生效。
      </p>
    </div>

    <div v-for="(relationship, index) in localRelationships" :key="index" class="p-4 border border-gray-200 rounded-lg bg-gray-50 relative">
      <button @click="removeRelationship(index)" class="absolute top-2 right-2 text-red-400 hover:text-red-600 transition-colors p-1">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm4 0a1 1 0 012 0v6a1 1 0 11-2 0V8z" clip-rule="evenodd" />
        </svg>
      </button>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-2">
        <div>
          <label class="block text-sm font-medium text-gray-600 mb-1">从</label>
          <!-- 有角色列表时用下拉，避免手打错名字导致关系失效 -->
          <select
            v-if="characterNames.length"
            v-model="relationship.character_from"
            class="w-full p-1.5 border-b-2 border-gray-300 focus:border-indigo-500 outline-none transition bg-transparent text-sm"
          >
            <option value="">（请选择角色）</option>
            <option v-for="name in optionsFor(relationship.character_from)" :key="name" :value="name">
              {{ name }}
            </option>
          </select>
          <input
            v-else
            type="text"
            v-model="relationship.character_from"
            class="w-full p-1 border-b-2 border-gray-300 focus:border-indigo-500 outline-none transition bg-transparent"
            placeholder="例如：林远"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-600 mb-1">到</label>
          <select
            v-if="characterNames.length"
            v-model="relationship.character_to"
            class="w-full p-1.5 border-b-2 border-gray-300 focus:border-indigo-500 outline-none transition bg-transparent text-sm"
          >
            <option value="">（请选择角色）</option>
            <option v-for="name in optionsFor(relationship.character_to)" :key="name" :value="name">
              {{ name }}
            </option>
          </select>
          <input
            v-else
            type="text"
            v-model="relationship.character_to"
            class="w-full p-1 border-b-2 border-gray-300 focus:border-indigo-500 outline-none transition bg-transparent"
            placeholder="例如：苏晴"
          />
        </div>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-600 mb-1">关系描述</label>
        <textarea
          v-model="relationship.description"
          class="w-full h-20 p-2 mt-1 border border-gray-300 rounded-md focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 transition text-sm"
          placeholder="关于这段关系的详细描述..."
        ></textarea>
      </div>
    </div>
    <button @click="addRelationship" class="w-full mt-4 px-4 py-2 text-sm font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 rounded-md hover:bg-indigo-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
      + 添加新关系
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, defineProps, defineEmits, nextTick } from 'vue';

interface Relationship {
  character_from: string;
  character_to: string;
  description: string;
}

const props = defineProps({
  modelValue: {
    type: Array as () => Relationship[],
    default: () => []
  },
  /**
   * 可选的「主要角色」名单。
   *
   * 关系在数据库里是按【角色名】关联的（character_from / character_to 都是
   * 字符串），所以名字必须与角色表完全一致，否则这条关系指向一个不存在的
   * 角色，而且不会有任何报错。用手打很容易出错，所以有名单时改用下拉。
   */
  characters: {
    type: Array as () => Array<{ name?: string } | string>,
    default: () => []
  }
});

const emit = defineEmits(['update:modelValue']);

const localRelationships = ref<Relationship[]>([]);
let syncing = false;

/** 归一化成纯名字列表，过滤空值。 */
const characterNames = computed<string[]>(() =>
  props.characters
    .map((c) => (typeof c === 'string' ? c : c?.name ?? ''))
    .map((n) => n.trim())
    .filter(Boolean)
);

/**
 * 下拉选项：已有角色 + 当前值（若当前值不在名单里）。
 *
 * 必须把「孤儿值」也列出来，否则一个指向已删除角色的关系会因为
 * select 找不到匹配 option 而被浏览器静默显示成第一项，
 * 用户一保存就把数据改错了。
 */
const optionsFor = (current: string): string[] => {
  const names = characterNames.value;
  if (current && !names.includes(current)) {
    return [current, ...names];
  }
  return names;
};

/** 关系里指向了不存在的角色的那些名字。 */
const orphanNames = computed<string[]>(() => {
  if (!characterNames.value.length) return [];
  const known = new Set(characterNames.value);
  const bad = new Set<string>();
  for (const rel of localRelationships.value) {
    for (const value of [rel.character_from, rel.character_to]) {
      const name = (value || '').trim();
      if (name && !known.has(name)) bad.add(name);
    }
  }
  return [...bad];
});

watch(() => props.modelValue, (newVal) => {
  syncing = true;
  localRelationships.value = JSON.parse(JSON.stringify(newVal || []));
  nextTick(() => {
    syncing = false;
  });
}, { immediate: true });

watch(localRelationships, (newVal) => {
  if (syncing) return;
  emit('update:modelValue', JSON.parse(JSON.stringify(newVal)));
}, { deep: true });

const addRelationship = () => {
  localRelationships.value.push({
    character_from: '',
    character_to: '',
    description: ''
  });
};

const removeRelationship = (index: number) => {
  localRelationships.value.splice(index, 1);
};
</script>
