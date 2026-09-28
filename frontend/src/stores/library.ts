import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { FavoriteItem, HistoryItem } from '@/types';

export const useLibraryStore = defineStore('library', () => {
  const favorites = ref<FavoriteItem[]>([]);
  const history = ref<HistoryItem[]>([]);
  const watchedMap = ref<Record<string, string[]>>({});
  const isLoading = ref(false);

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

  async function toggleFavorite(payload: {
    url: string;
    title: string;
    imageUrl: string;
    source: string;
    autoDownload?: boolean;
  }) {
    const isFav = favorites.value.some((f) => f.url === payload.url);
    if (isFav) {
      await api.removeFavorite(payload.url);
    } else {
      await api.addFavorite(payload);
    }
    await fetchFavorites();
    return { isFavorite: !isFav };
  }

  async function toggleAutoDownload(url: string, current: boolean) {
    const res = await api.toggleAutoDownload(url, !current);
    const item = favorites.value.find((f) => f.url === url);
    if (item) item.autoDownload = !current;
    return res;
  }

  async function clearAllFavorites() {
    const res = await api.clearAllFavorites();
    await fetchFavorites();
    return res;
  }

  async function markWatched(animeUrl: string, episodeNumber: string | number, watched: boolean) {
    const epStr = String(episodeNumber);
    await api.markEpisodeWatched({ animeUrl, episodeNumber: epStr, watched });
    if (!watchedMap.value[animeUrl]) {
      watchedMap.value[animeUrl] = [];
    }
    const list = watchedMap.value[animeUrl];
    if (watched && !list.includes(epStr)) {
      list.push(epStr);
    } else if (!watched) {
      watchedMap.value[animeUrl] = list.filter((n) => n !== epStr);
    }
  }

  function isWatched(animeUrl: string, episodeNumber: string | number): boolean {
    const epStr = String(episodeNumber);
    const list = watchedMap.value[animeUrl];
    return list ? list.includes(epStr) : false;
  }

  return {
    favorites,
    history,
    watchedMap,
    isLoading,
    fetchFavorites,
    toggleFavorite,
    toggleAutoDownload,
    clearAllFavorites,
    markWatched,
    isWatched,
  };
});
