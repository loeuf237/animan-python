<template>
  <div style="margin-top:16px">
    <h3>{{ tx('Historique des recettes') }}</h3>
    <p>{{ tx('Les 20 dernières recettes sont conservées. Restaurer une recette crée une nouvelle révision.') }}</p>
    <p v-if="message" role="status">{{ tx(message) }}</p>
    <ul style="padding-left:20px">
      <li v-for="revision in revisions" :key="revision.revision" style="margin:8px 0;overflow-wrap:anywhere">
        r{{ revision.revision }} · {{ new Date(revision.created_at.replace(' ', 'T')+'Z').toLocaleString() }}
        <button class="btn btn-sm" :disabled="busy || revision.revision===revisions[0]?.revision" @click="restore(revision.revision)">{{ tx('Restaurer') }}</button>
      </li>
    </ul>
  </div>
</template>
<script setup lang="ts">
import { ref,onMounted } from 'vue';
import { api } from '@/api/client';
import type { RecipeRevision } from '@/types/api';
import { tx } from '@/utils/locale';
const props=defineProps<{extensionId: string | number}>();
const emit=defineEmits<{restored:[]}>();
const revisions=ref<RecipeRevision[]>([]),busy=ref(false),message=ref('');
async function load() {
  try { revisions.value=(await api.getRecipeHistory(props.extensionId)).revisions; }
  catch { message.value='Historique indisponible.'; }
}
async function restore(revision: number) {
  busy.value=true;message.value='';
  try { await api.restoreRecipe(props.extensionId,revision);await load();emit('restored');message.value='Recette restaurée.'; }
  catch { message.value='Impossible de restaurer cette recette. Vérifiez son adresse et ses sélecteurs.'; }
  finally {busy.value=false;}
}
onMounted(load);
</script>
