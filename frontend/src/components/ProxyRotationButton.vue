<template>
  <span class="proxy-rotation-action">
    <button class="btn btn-secondary btn-sm" :disabled="busy" @click="rotate">{{ tx(busy ? 'Rotation en cours…' : 'Changer de proxy et réessayer') }}</button>
    <span v-if="error" role="alert">{{ tx(error) }} <router-link to="/settings?tab=proxy">{{ tx('Paramètres du proxy') }}</router-link></span>
  </span>
</template>
<script setup lang="ts">
import { ref } from 'vue';
import { api } from '@/api/client';
import { tx } from '@/utils/locale';
const props = defineProps<{domain: string; retry?: () => Promise<void>}>();
const busy = ref(false), error = ref('');
async function rotate() {
  if (busy.value) return;
  busy.value = true; error.value = '';
  try { await api.rotateSourceProxy(props.domain); await props.retry?.(); }
  catch (exc) { error.value = exc instanceof Error ? exc.message : 'Rotation impossible.'; }
  finally { busy.value = false; }
}
</script>
<style scoped>
.proxy-rotation-action { display: inline-flex; flex-direction: column; gap: 8px; max-width: 100%; }
.proxy-rotation-action > span { font-size: .85rem; color: var(--red); overflow-wrap: anywhere; }
</style>
