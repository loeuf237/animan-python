<template>
  <div class="library-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ tx('Ma Bibliothèque') }}</h1>
        <p class="page-sub">
          {{
            tx('Gérez vos séries favorites et la surveillance automatique des nouveaux épisodes.')
          }}
        </p>
      </div>

      <div style="display: flex; gap: 10px">
        <details v-if="favorites.length" class="library-options">
          <summary class="btn">Options</summary>
          <button type="button" class="btn btn-danger" @click="clearDialogOpen = true">
            {{ tx('Vider la bibliothèque') }}
          </button>
        </details>
        <button class="btn btn-primary" @click="libraryStore.fetchFavorites">
          {{ tx('Actualiser') }}
        </button>
      </div>
    </div>

    <!-- Stats Bar -->
    <div class="stats-grid" style="margin-bottom: 24px">
      <div class="stat-card">
        <strong>{{ tx(favorites.length) }}</strong>
        <span>{{ tx('Séries suivies') }}</span>
      </div>
      <div class="stat-card stat-blue">
        <strong>{{ tx(autoDownloadCount) }}</strong>
        <span>{{ tx('Téléchargement auto actif') }}</span>
      </div>
      <div class="stat-card stat-green">
        <strong>{{ tx(distinctSourcesCount) }}</strong>
        <span>{{ tx('Sources représentées') }}</span>
      </div>
    </div>

    <p v-if="libraryStore.favoritesError" role="alert">{{ tx(libraryStore.favoritesError) }}</p>
    <p v-if="libraryStore.isLoading && !favorites.length" role="status">
      {{ tx('Chargement de la bibliothèque…') }}
    </p>
    <!-- Empty State -->
    <div
      v-if="!libraryStore.isLoading && !libraryStore.favoritesError && favorites.length === 0"
      class="empty-state"
    >
      <h3>{{ tx('Aucun animé dans votre bibliothèque') }}</h3>
      <p>
        {{
          tx('Parcourez les sorties ou utilisez la recherche pour ajouter des séries en favoris.')
        }}
      </p>
      <router-link to="/" class="btn btn-primary" style="margin-top: 14px">{{
        tx('Découvrir les animés')
      }}</router-link>
    </div>

    <!-- Favorites Grid -->
    <div v-else class="results-grid animate-fade-in">
      <article v-for="fav in favorites" :key="fav.url" class="anime-card">
        <router-link
          :to="{ path: '/anime', query: { url: fav.url, source: fav.source || 'french-manga' } }"
          class="card-link"
        >
          <div class="card-poster">
            <img :src="fav.imageUrl" :alt="tx(fav.title)" loading="lazy" />
            <div class="card-overlay">
              <span class="fav-badge">{{ tx('Favori') }}</span>
              <span v-if="fav.autoDownload" class="chip chip-auto">Auto-DL</span>
            </div>
          </div>
          <div class="card-info">
            <h3 class="card-title">{{ tx(fav.title) }}</h3>
            <span class="card-sub">{{ tx(fav.source || 'french-manga') }}</span>
          </div>
        </router-link>

        <!-- Card Footer Actions -->
        <div
          style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            border-top: 1px solid var(--line);
          "
        >
          <label
            style="
              display: flex;
              align-items: center;
              gap: 6px;
              font-size: 12px;
              color: var(--muted);
              cursor: pointer;
            "
          >
            <input type="checkbox" :checked="fav.autoDownload" @change="toggleAuto(fav)" />
            <span>Auto-DL</span>
          </label>

          <button
            class="icon-button"
            style="width: 32px; height: 32px"
            :title="tx('Retirer de la bibliothèque')"
            :aria-label="tx(`Retirer ${fav.title} de la bibliothèque`)"
            @click="removeFav(fav)"
          >
            ✕
          </button>
        </div>
        <AutoDownloadPreferences v-if="fav.autoDownload" :favorite="fav" />
      </article>
    </div>
    <ConfirmDialog
      :open="clearDialogOpen"
      :title="tx('Vider la bibliothèque ?')"
      :confirm-label="tx('Vider')"
      :busy="clearing"
      danger
      @cancel="clearDialogOpen = false"
      @confirm="clearAll"
      ><p>
        {{
          tx(
            'Les séries seront retirées de votre bibliothèque. Les fichiers téléchargés seront conservés.',
          )
        }}
      </p></ConfirmDialog
    >
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, computed, onMounted, onActivated } from 'vue'
import { useLibraryStore } from '@/stores/library'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import AutoDownloadPreferences from '@/components/AutoDownloadPreferences.vue'
import { useNotifications } from '@/stores/notifications'
import type { FavoriteItem } from '@/types'

defineOptions({ name: 'LibraryView' })
const libraryStore = useLibraryStore(),
  notifications = useNotifications()
const clearDialogOpen = ref(false),
  clearing = ref(false)
let firstActivation = true
onActivated(() => {
  if (firstActivation) firstActivation = false
  else void libraryStore.fetchFavorites()
})

onMounted(() => {
  libraryStore.fetchFavorites()
})

const favorites = computed<FavoriteItem[]>(() => {
  return libraryStore.favorites
})

const autoDownloadCount = computed(() => {
  return favorites.value.filter((f) => f.autoDownload).length
})

const distinctSourcesCount = computed(() => {
  const s = new Set(favorites.value.map((f) => f.source))
  return s.size
})

function toggleAuto(fav: FavoriteItem) {
  void libraryStore.toggleAutoDownload(fav.url, fav.autoDownload).catch(() => {})
}

function removeFav(fav: FavoriteItem) {
  void libraryStore
    .toggleFavorite({
      url: fav.url,
      title: fav.title,
      imageUrl: fav.imageUrl,
      source: fav.source,
    })
    .catch((error) =>
      notifications.notify(error.message || 'Impossible de retirer cette série.', 'error'),
    )
}

async function clearAll() {
  clearing.value = true
  try {
    await libraryStore.clearAllFavorites()
    clearDialogOpen.value = false
  } catch (error) {
    notifications.notify(
      error instanceof Error ? error.message : 'Impossible de vider la bibliothèque.',
      'error',
    )
  } finally {
    clearing.value = false
  }
}
</script>

<style scoped>
.library-container {
  display: flex;
  flex-direction: column;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--muted);
  text-align: center;
}
</style>
