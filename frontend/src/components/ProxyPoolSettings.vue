<template>
  <section class="settings-card-pro proxy-auto-card">
    <header class="settings-card-header-pro">
      <div>
        <h2 class="settings-card-title-pro">{{ tx('Auto · Liste de proxys publics') }}</h2>
        <p class="settings-card-sub-pro">
          {{
            tx(
              'La liste est actualisée au lancement. Seuls les proxys ayant réussi un test HTTPS récent sont utilisés pour la rotation.',
            )
          }}
        </p>
      </div>
    </header>
    <div class="proxy-auto-content">
      <label class="proxy-auto-toggle">
        <input
          type="checkbox"
          :checked="pool?.automatic || false"
          :disabled="busy || !pool"
          @change="setAutomatic"
        />
        <span
          ><strong>{{ tx('Rotation automatique des sources bloquées') }}</strong
          ><small>{{
            tx(
              'S’applique aux catalogues, aux recherches et aux téléchargements. Deux changements maximum par domaine en cinq minutes ; aucun changement pendant un transfert en cours.',
            )
          }}</small></span
        >
      </label>
      <p class="proxy-help">
        {{
          tx(
            'Les proxys publics peuvent être lents ou refusés par un site. Une rotation ne garantit pas la résolution d’un captcha.',
          )
        }}
      </p>
      <div class="proxy-toolbar">
        <button
          class="btn btn-secondary"
          :disabled="busy || pool?.refreshing || pool?.checking"
          @click="perform(api.refreshProxyPool)"
        >
          {{ tx('Actualiser les listes') }}
        </button>
        <button
          class="btn btn-secondary"
          :disabled="busy || !pool?.total || pool?.refreshing || pool?.checking"
          @click="perform(api.checkProxyPool)"
        >
          {{ tx('Tester un échantillon') }}
        </button>
        <label class="btn btn-secondary proxy-import" :class="{ disabled: busy }"
          >{{ tx('Importer un JSON')
          }}<input
            type="file"
            accept="application/json,.json"
            :disabled="busy"
            @change="importFile"
        /></label>
        <button
          v-if="pool?.importedCount"
          class="btn btn-secondary"
          :disabled="busy"
          @click="perform(api.clearImportedProxies)"
        >
          {{ tx('Retirer la liste importée') }}
        </button>
      </div>
      <p v-if="busy || pool?.refreshing || pool?.checking" role="status">
        {{ tx('Actualisation ou tests en cours…') }}
      </p>
      <p v-if="error" class="proxy-error" role="alert">{{ tx(error) }}</p>
      <p v-if="notice" role="status">{{ tx(notice) }}</p>
      <p v-if="pool" class="proxy-summary">
        <strong>{{ pool.healthy }} {{ tx('proxys HTTPS disponibles') }}</strong> · {{ pool.total }}
        {{ tx('adresses dans le catalogue')
        }}<span v-if="pool.lastRefresh">
          · {{ tx('Actualisé :') }} {{ new Date(pool.lastRefresh * 1000).toLocaleString() }}</span
        >
      </p>
      <ul class="proxy-providers">
        <li v-for="provider in pool?.providers" :key="provider.id">
          <a :href="provider.website" target="_blank" rel="noopener noreferrer">{{
            provider.name
          }}</a>
          <span
            >{{ provider.count || 0 }} {{ tx('adresses') }} ·
            {{
              tx(
                provider.status === 'ok'
                  ? 'Liste actualisée'
                  : provider.status === 'error'
                    ? 'Fournisseur indisponible'
                    : 'En attente',
              )
            }}</span
          >
          <small v-if="provider.error">{{ tx(provider.error) }}</small>
        </li>
      </ul>
      <details>
        <summary>{{ tx('Format du fichier JSON') }}</summary>
        <p>
          {{
            tx(
              'Tableau d’URL de proxys, ou objet avec une liste proxies/data. Les objets peuvent contenir ip, port et protocol. Limites : 1 Mo, 1 000 adresses IP publiques. Les adresses locales et les noms de domaine se configurent dans Manuel.',
            )
          }}
        </p>
      </details>
      <details v-if="pool?.entries.length" class="proxy-catalogue">
        <summary>{{ tx('Voir les adresses de proxy') }}</summary>
        <div class="proxy-list" role="list" :aria-label="tx('Catalogue des proxys')">
          <div v-for="entry in pool.entries" :key="entry.url" class="proxy-entry" role="listitem">
            <code>{{ entry.url }}</code
            ><span>{{ entry.country || '—' }} · {{ entry.provider }}</span>
            <span :class="{ 'proxy-available': entry.usable }"
              >{{
                tx(
                  entry.usable
                    ? 'Disponible'
                    : entry.status === 'ok'
                      ? 'Test expiré'
                      : entry.status === 'failed'
                        ? 'Échec du test'
                        : 'Non testé',
                )
              }}<template v-if="entry.usable"> · {{ entry.latencyMs }} ms</template></span
            >
          </div>
        </div>
        <small v-if="pool && pool.total > pool.entries.length">{{
          tx('Les 100 premières adresses sont affichées, avec les proxys disponibles en premier.')
        }}</small>
      </details>
      <p v-if="pool && !pool.total">
        {{
          tx('Aucune liste disponible. Actualisez les fournisseurs ou importez votre fichier JSON.')
        }}
      </p>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { api, type ProxyPoolSnapshot } from '@/api/client'
import { tx } from '@/utils/locale'
const props = defineProps<{ active: boolean }>()
const pool = ref<ProxyPoolSnapshot | null>(null)
const busy = ref(false),
  error = ref(''),
  notice = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
async function load() {
  try {
    pool.value = await api.getProxyPool()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Catalogue indisponible.'
  }
  if (!disposed && props.active && (pool.value?.refreshing || pool.value?.checking))
    timer = setTimeout(load, 2500)
}
watch(
  () => props.active,
  (active) => {
    clearTimeout(timer)
    if (active) void load()
  },
  { immediate: true },
)
onUnmounted(() => {
  disposed = true
  clearTimeout(timer)
})
async function perform(action: () => Promise<ProxyPoolSnapshot>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    pool.value = await action()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Action impossible.'
  } finally {
    busy.value = false
  }
}
async function setAutomatic(event: Event) {
  const enabled = (event.target as HTMLInputElement).checked
  await perform(() => api.saveProxyPool(enabled))
  ;(event.target as HTMLInputElement).checked = pool.value?.automatic || false
}
async function importFile(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0]
  if (!file || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (file.size > 1024 * 1024) throw new Error('Le fichier JSON dépasse 1 Mo')
    let data: unknown
    try {
      data = JSON.parse(await file.text())
    } catch {
      throw new Error('Fichier JSON invalide.')
    }
    const result = await api.importProxyPool(data)
    pool.value = result.pool
    notice.value = `${result.imported} proxys importés. Testez un échantillon avant de les utiliser.`
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Import impossible.'
  } finally {
    busy.value = false
    input.value = ''
  }
}
</script>
<style scoped>
.proxy-auto-card {
  margin-bottom: 24px;
}
.proxy-auto-content {
  padding: 0 24px 24px;
  display: grid;
  gap: 16px;
  min-width: 0;
}
.proxy-auto-content p {
  margin: 0;
}
.proxy-catalogue summary {
  cursor: pointer;
}
.proxy-catalogue .proxy-list {
  margin-top: 10px;
}
.proxy-auto-toggle {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  cursor: pointer;
}
.proxy-auto-toggle input {
  margin-top: 4px;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  accent-color: var(--accent);
}
.proxy-auto-toggle small {
  display: block;
  color: var(--muted);
  margin-top: 5px;
  line-height: 1.5;
}
.proxy-help,
.proxy-summary,
details {
  color: var(--muted);
  line-height: 1.5;
}
.proxy-toolbar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.proxy-import {
  position: relative;
  overflow: hidden;
  cursor: pointer;
}
.proxy-import input {
  position: absolute;
  inset: 0;
  width: 100%;
  opacity: 0;
  cursor: pointer;
}
.proxy-import.disabled {
  opacity: 0.5;
}
.proxy-providers {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.proxy-providers li {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.proxy-providers small {
  width: 100%;
}
.proxy-providers a {
  font-weight: 600;
}
.proxy-list {
  max-height: 350px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}
.proxy-entry {
  padding: 12px;
  border-bottom: 1px solid var(--border);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px;
  font-size: 0.85rem;
}
.proxy-entry code {
  overflow-wrap: anywhere;
  grid-column: 1/-1;
}
.proxy-entry span {
  overflow-wrap: anywhere;
}
.proxy-available {
  color: var(--green);
}
.proxy-error {
  color: var(--red);
}
@media (max-width: 480px) {
  .proxy-auto-content {
    padding: 0 16px 16px;
  }
  .proxy-entry {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
