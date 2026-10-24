<template>
  <div v-if="visible" class="export-notice" :class="{ 'export-warning': retryable }" role="status">
    <strong>{{ tx(label) }}</strong>
    <details v-if="task.exportDestination">
      <summary>{{ tx('Voir l’emplacement') }}</summary>
      <span>{{ task.exportDestination }}</span>
    </details>
    <span v-if="retryable">{{
      tx('La vidéo vérifiée reste disponible dans la bibliothèque.')
    }}</span>
    <details v-if="task.exportError">
      <summary>{{ tx('Détail de l’export') }}</summary>
      {{ tx(task.exportError) }}
    </details>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { DownloadTask } from '@/types'
import { tx } from '@/utils/locale'
const props = defineProps<{ task: DownloadTask; native?: boolean }>()
const retryable = computed(
  () => props.task.exportStatus === 'EXPORT_FAILED' || props.task.exportStatus === 'PENDING',
)
const visible = computed(
  () =>
    props.task.exportStatus === 'EXPORTING' ||
    props.task.exportStatus === 'EXPORTED' ||
    (props.task.status === 'completed' && (retryable.value || props.native)),
)
const label = computed(
  () =>
    ({
      EXPORTING: 'Copie vers le stockage en cours',
      EXPORTED: 'Exporté vers le stockage',
      EXPORT_FAILED: 'Export à reprendre',
      PENDING: 'Export à reprendre',
      NOT_REQUESTED: 'Export non renseigné',
    })[props.task.exportStatus || 'NOT_REQUESTED'],
)
</script>
<style scoped>
.export-notice {
  display: grid;
  gap: 4px;
  padding: 10px;
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}
.export-warning {
  border-color: var(--warning, #d97706);
}
.export-notice span {
  color: var(--muted);
}
.export-notice summary {
  cursor: pointer;
  min-height: 44px;
  display: flex;
  align-items: center;
  text-decoration: underline;
}
</style>
