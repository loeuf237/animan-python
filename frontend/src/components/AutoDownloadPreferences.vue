<template>
  <details class="follow-options">
    <summary>{{ tx('Réglages du suivi automatique') }}</summary>
    <div class="follow-fields">
      <label>{{ tx('Version suivie') }}
        <select v-model="version" class="input-premium">
          <option value="">{{ tx('Version de la fiche (si non ambiguë)') }}</option>
          <option value="*">{{ tx('Toutes les versions') }}</option>
          <option v-for="item in versions" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label>{{ tx('Qualité demandée') }}
        <select v-model="quality" class="input-premium">
          <option value="">{{ tx('Automatique') }}</option>
          <option v-for="item in qualities" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label>{{ tx('Lecteur préféré (facultatif)') }}
        <input v-model="server" class="input-premium" maxlength="100" :placeholder="tx('Automatique')" />
      </label>
      <label class="follow-subtitles"><input type="checkbox" v-model="subtitles" />{{ tx('Télécharger les sous-titres') }}</label>
      <p class="follow-hint">{{ tx('Les versions non suivies ne sont pas téléchargées. Les anciens épisodes restent disponibles depuis la fiche.') }}</p>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="saving" @click="save">{{ tx('Enregistrer le suivi') }}</button>
      <p v-if="message" role="status">{{ tx(message) }}</p>
    </div>
  </details>
  <p v-if="favorite.autoDownloadError" class="follow-error" role="status">{{ tx(favorite.autoDownloadError) }}</p>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { FavoriteItem } from '@/types';
import { useLibraryStore } from '@/stores/library';
import { tx } from '@/utils/locale';

const props = defineProps<{ favorite: FavoriteItem }>();
const store = useLibraryStore();
const version = ref(''), quality = ref(''), server = ref(''), subtitles = ref(false);
const saving = ref(false), message = ref('');
const versions = computed(() => [...new Set(['VF', 'VOSTFR', 'VO', 'VOSTEN', props.favorite.autoDownloadVersion || ''])].filter(v => v && v !== '*'));
const qualities = computed(() => [...new Set(['1080p', '720p', '480p', props.favorite.autoDownloadQuality || ''])].filter(Boolean));
watch(() => props.favorite, favorite => {
  version.value = favorite.autoDownloadVersion || '';
  quality.value = favorite.autoDownloadQuality || '';
  server.value = favorite.autoDownloadServer || '';
  subtitles.value = !!favorite.autoDownloadSubtitles;
}, { immediate: true, deep: true });
async function save() {
  saving.value = true;
  message.value = '';
  try {
    await store.saveAutoDownload(props.favorite, { autoDownloadVersion: version.value,
      autoDownloadQuality: quality.value || null, autoDownloadServer: server.value.trim() || null,
      autoDownloadSubtitles: subtitles.value });
    message.value = 'Réglages du suivi enregistrés.';
  } catch (error) { message.value = error instanceof Error ? error.message : 'Impossible de modifier le suivi.'; }
  finally { saving.value = false; }
}
</script>

<style scoped>
.follow-options { margin: 0 14px 14px; font-size: .85rem; min-width: 0; }
.follow-options summary { cursor: pointer; color: var(--muted); }
.follow-fields { display: grid; gap: 10px; padding-top: 12px; }
.follow-fields label { display: grid; gap: 5px; min-width: 0; }
.follow-fields select, .follow-fields input { width: 100%; min-width: 0; }
.follow-fields .follow-subtitles { display: flex; align-items: center; gap: 8px; }
.follow-subtitles input { width: auto; }
.follow-hint { color: var(--muted); margin: 0; }
.follow-error { margin: 0 14px 14px; color: var(--danger, #dc2626); font-size: .85rem; overflow-wrap: anywhere; }
</style>
