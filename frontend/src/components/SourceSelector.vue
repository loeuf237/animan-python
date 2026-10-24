<template>
  <label class="source-selector" :for="id"
    ><span>{{ tx(label) }}</span>
    <select
      :id="id"
      :value="modelValue"
      @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    >
      <option v-if="includeAll" value="all">{{ tx('Toutes les sources') }}</option>
      <optgroup v-if="pinned.length" :label="tx('Épinglées')">
        <option v-for="source in pinned" :key="source.id" :value="source.id">
          {{ tx(source.name) }}
        </option>
      </optgroup>
      <optgroup v-if="others.length" :label="tx('Autres sources')">
        <option v-for="source in others" :key="source.id" :value="source.id">
          {{ tx(source.name) }}
        </option>
      </optgroup>
    </select>
  </label>
</template>
<script setup lang="ts">
import { tx } from '@/utils/locale'
import { computed, useId } from 'vue'
import { useSourcePreferences } from '@/stores/sourcePreferences'
const props = withDefaults(
  defineProps<{
    modelValue: string
    sources: { id: string; name: string }[]
    label?: string
    includeAll?: boolean
  }>(),
  { label: 'Source', includeAll: true },
)
defineEmits<{ (event: 'update:modelValue', value: string): void }>()
const preferences = useSourcePreferences(),
  id = useId()
const pinned = computed(() =>
  props.sources.filter((source) => preferences.pinned.includes(source.id)),
)
const others = computed(() =>
  props.sources.filter((source) => !preferences.pinned.includes(source.id)),
)
</script>
