<template>
  <section class="settings-card-pro diagnostics-card">
    <h2>{{ tx('Diagnostics') }}</h2>
    <p>
      {{
        tx(
          'Exportez les événements récents et les durées des opérations pour comprendre un problème. Les cookies, mots de passe et adresses vidéo ne sont pas inclus.',
        )
      }}
    </p>
    <button class="btn" :disabled="busy" @click="download">
      {{ tx(busy ? 'Export en cours…' : 'Exporter les diagnostics') }}
    </button>
    <p v-if="message" role="status">{{ tx(message) }}</p>
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import { tx } from '@/utils/locale'
const busy = ref(false),
  message = ref('')
async function download() {
  busy.value = true
  message.value = ''
  let url: string | null = null
  try {
    const report = await api.getDiagnostics()
    url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }),
    )
    const link = document.createElement('a')
    link.href = url
    link.download = 'animelab-diagnostics.json'
    document.body.appendChild(link)
    link.click()
    link.remove()
    message.value = 'Diagnostics exportés.'
  } catch {
    message.value =
      'Impossible d’exporter les diagnostics. Ouvrez AnimeLab sur l’appareil qui exécute le serveur.'
  } finally {
    busy.value = false
    if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000)
  }
}
</script>

<style scoped>
.diagnostics-card {
  padding: 24px;
}
@media (max-width: 768px) {
  .diagnostics-card {
    padding: 14px;
  }
}
</style>
