import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import { useNotifications } from '@/stores/notifications'
import type { AutoDownloadOptions, FavoriteItem, HistoryItem } from '@/types'

export const useLibraryStore = defineStore('library', () => {
  const favorites = ref<FavoriteItem[]>([])
  const history = ref<HistoryItem[]>([])
  const watchedMap = ref<Record<string, Record<string, boolean>>>({})
  const isLoading = ref(false)
  const isLoadingHistory = ref(false)
  const favoritesError = ref('')
  const notifications = useNotifications()

  async function fetchFavorites() {
    isLoading.value = true
    favoritesError.value = ''
    try {
      const res = await api.getFavorites()
      if (Array.isArray(res)) {
        favorites.value = res
      }
    } catch (e) {
      favoritesError.value =
        e instanceof Error ? e.message : 'Impossible de charger la bibliothèque.'
      console.error('[LibraryStore] fetchFavorites error:', e)
    } finally {
      isLoading.value = false
    }
  }

  async function fetchHistory(animeName?: string) {
    isLoadingHistory.value = true
    try {
      const res = await api.getHistory(animeName)
      if (Array.isArray(res)) {
        history.value = res
      }
    } catch (e) {
      console.error('[LibraryStore] fetchHistory error:', e)
    } finally {
      isLoadingHistory.value = false
    }
  }

  async function loadWatchedForAnime(animeUrl: string) {
    if (!animeUrl) return
    try {
      const progressList = await api.getProgress(animeUrl)
      if (Array.isArray(progressList)) {
        if (!watchedMap.value[animeUrl]) {
          watchedMap.value[animeUrl] = {}
        }
        for (const p of progressList) {
          const epNum = p.episodeNumber ?? p.episode_number
          const ver = p.version || ''
          if (epNum !== undefined && epNum !== null) {
            watchedMap.value[animeUrl][`${epNum}-${ver}`] = p.isWatched ?? p.watched ?? true
          }
        }
      }
    } catch (e) {
      console.debug('[LibraryStore] loadWatchedForAnime error:', e)
    }
  }

  async function toggleFavorite(
    payload: {
      url: string
      title: string
      imageUrl: string
      source: string
      autoDownload?: boolean
    } & AutoDownloadOptions,
  ) {
    if (isLoading.value && favorites.value.length === 0) {
      await fetchFavorites()
    }
    const isFav = favorites.value.some((f) => f.url === payload.url)
    const previous = favorites.value.find((f) => f.url === payload.url)
    try {
      if (isFav) {
        await api.removeFavorite(payload.url)
      } else {
        await api.addFavorite(payload)
      }
      await fetchFavorites()
      if (isFav) {
        const saved = { ...payload, ...previous }
        notifications.notify(`${payload.title} retiré de la bibliothèque.`, 'info', {
          label: 'Annuler',
          async run() {
            // Restoring twice must never toggle the favorite off again.
            if (!favorites.value.some((f) => f.url === saved.url)) await api.addFavorite(saved)
            await fetchFavorites()
          },
        })
      } else notifications.notify(`${payload.title} ajouté à la bibliothèque.`)
      return { isFavorite: !isFav }
    } catch (e) {
      console.error('[LibraryStore] toggleFavorite error:', e)
      throw e
    }
  }

  async function toggleAutoDownload(
    url: string,
    current: boolean,
    options: AutoDownloadOptions = {},
  ) {
    const item = favorites.value.find((f) => f.url === url)
    const targetState = !current
    if (item) item.autoDownload = targetState
    try {
      const res = await api.toggleAutoDownload(url, targetState, options)
      if (item && res.favorite) Object.assign(item, res.favorite)
      notifications.notify(`Téléchargement automatique ${targetState ? 'activé' : 'désactivé'}.`)
      return res
    } catch (e) {
      if (item) item.autoDownload = current // Rollback
      notifications.notify(
        e instanceof Error ? e.message : 'Impossible de modifier le téléchargement automatique.',
        'error',
      )
      console.error('[LibraryStore] toggleAutoDownload error:', e)
      throw e
    }
  }

  async function saveAutoDownload(favorite: FavoriteItem, options: AutoDownloadOptions) {
    const res = await api.toggleAutoDownload(favorite.url, favorite.autoDownload, options)
    const item = favorites.value.find((f) => f.url === favorite.url)
    if (item && res.favorite) Object.assign(item, res.favorite)
    return res
  }

  async function clearAllFavorites() {
    const previous = favorites.value.map((item) => ({ ...item }))
    const res = await api.clearAllFavorites()
    await fetchFavorites()
    notifications.notify('Bibliothèque vidée.', 'info', {
      label: 'Annuler',
      async run() {
        for (const item of previous) {
          if (!favorites.value.some((favorite) => favorite.url === item.url))
            await api.addFavorite(item)
        }
        await fetchFavorites()
      },
    })
    return res
  }

  async function markWatched(
    animeUrl: string,
    episodeNumber: string | number,
    watched: boolean,
    version = '',
    animeName = '',
  ) {
    const epStr = String(episodeNumber)
    const key = `${epStr}-${version}`
    if (!watchedMap.value[animeUrl]) {
      watchedMap.value[animeUrl] = {}
    }
    const previous = watchedMap.value[animeUrl][key]
    // Mise à jour optimiste
    watchedMap.value[animeUrl][key] = watched

    try {
      await api.markEpisodeWatched({ animeUrl, animeName, episodeNumber: epStr, watched, version })
    } catch (e) {
      // Rollback en cas d'échec
      if (previous !== undefined) {
        watchedMap.value[animeUrl][key] = previous
      } else {
        delete watchedMap.value[animeUrl][key]
      }
      console.error('[LibraryStore] markWatched error:', e)
      throw e
    }
  }

  function isWatched(
    animeUrl: string,
    episodeNumber: string | number,
    version = '',
  ): boolean | undefined {
    return watchedMap.value[animeUrl]?.[`${episodeNumber}-${version}`]
  }

  return {
    favorites,
    history,
    watchedMap,
    isLoading,
    isLoadingHistory,
    favoritesError,
    fetchFavorites,
    fetchHistory,
    loadWatchedForAnime,
    toggleFavorite,
    toggleAutoDownload,
    saveAutoDownload,
    clearAllFavorites,
    markWatched,
    isWatched,
  }
})
