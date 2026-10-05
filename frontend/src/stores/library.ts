import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { FavoriteItem, HistoryItem } from '@/types';

export const useLibraryStore = defineStore('library', () => {
  const favorites = ref<FavoriteItem[]>([]);
  const history = ref<HistoryItem[]>([]);
  const watchedMap = ref<Record<string, Record<string, boolean>>>({});
  const isLoading = ref(false);
  const isLoadingHistory = ref(false);

  async function fetchFavorites() {
    isLoading.value = true;
    try {
      const res = await api.getFavorites();
      if (Array.isArray(res)) {
        favorites.value = res;
      }
    } catch (e) {
      console.error('[LibraryStore] fetchFavorites error:', e);
    } finally {
      isLoading.value = false;
    }
  }

  async function fetchHistory(animeName?: string) {
    isLoadingHistory.value = true;
    try {
      const res = await api.getHistory(animeName);
      if (Array.isArray(res)) {
        history.value = res;
      }
    } catch (e) {
      console.error('[LibraryStore] fetchHistory error:', e);
    } finally {
      isLoadingHistory.value = false;
    }
  }

  async function loadWatchedForAnime(animeUrl: string) {
    if (!animeUrl) return;
    try {
      const progressList = await api.getProgress(animeUrl);
      if (Array.isArray(progressList)) {
        if (!watchedMap.value[animeUrl]) {
          watchedMap.value[animeUrl] = {};
        }
        for (const p of progressList) {
          const epNum = p.episodeNumber ?? p.episode_number;
          const ver = p.version || '';
          if (epNum !== undefined && epNum !== null) {
            watchedMap.value[animeUrl][`${epNum}-${ver}`] = p.isWatched ?? p.watched ?? true;
          }
        }
      }
    } catch (e) {
      console.debug('[LibraryStore] loadWatchedForAnime error:', e);
    }
  }

  async function toggleFavorite(payload: {
    url: string;
    title: string;
    imageUrl: string;
    source: string;
    autoDownload?: boolean;
  }) {
    if (isLoading.value && favorites.value.length === 0) {
      await fetchFavorites();
    }
    const isFav = favorites.value.some((f) => f.url === payload.url);
    try {
      if (isFav) {
        await api.removeFavorite(payload.url);
      } else {
        await api.addFavorite(payload);
      }
      await fetchFavorites();
      return { isFavorite: !isFav };
    } catch (e) {
      console.error('[LibraryStore] toggleFavorite error:', e);
      throw e;
    }
  }

  async function toggleAutoDownload(url: string, current: boolean) {
    const item = favorites.value.find((f) => f.url === url);
    const targetState = !current;
    if (item) item.autoDownload = targetState;
    try {
      const res = await api.toggleAutoDownload(url, targetState);
      return res;
    } catch (e) {
      if (item) item.autoDownload = current; // Rollback
      console.error('[LibraryStore] toggleAutoDownload error:', e);
      throw e;
    }
  }

  async function clearAllFavorites() {
    const res = await api.clearAllFavorites();
    await fetchFavorites();
    return res;
  }

  async function markWatched(animeUrl: string, episodeNumber: string | number, watched: boolean, version = '', animeName = '') {
    const epStr = String(episodeNumber);
    const key = `${epStr}-${version}`;
    if (!watchedMap.value[animeUrl]) {
      watchedMap.value[animeUrl] = {};
    }
    const previous = watchedMap.value[animeUrl][key];
    // Mise à jour optimiste
    watchedMap.value[animeUrl][key] = watched;

    try {
      await api.markEpisodeWatched({ animeUrl, animeName, episodeNumber: epStr, watched, version });
    } catch (e) {
      // Rollback en cas d'échec
      if (previous !== undefined) {
        watchedMap.value[animeUrl][key] = previous;
      } else {
        delete watchedMap.value[animeUrl][key];
      }
      console.error('[LibraryStore] markWatched error:', e);
      throw e;
    }
  }

  function isWatched(animeUrl: string, episodeNumber: string | number, version = ''): boolean | undefined {
    return watchedMap.value[animeUrl]?.[`${episodeNumber}-${version}`];
  }

  return {
    favorites,
    history,
    watchedMap,
    isLoading,
    isLoadingHistory,
    fetchFavorites,
    fetchHistory,
    loadWatchedForAnime,
    toggleFavorite,
    toggleAutoDownload,
    clearAllFavorites,
    markWatched,
    isWatched,
  };
});
