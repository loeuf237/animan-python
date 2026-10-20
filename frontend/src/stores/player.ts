import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { api } from '@/api/client';
import { episodeKey } from '@/utils/episodes';
import type { Episode, SubtitleTrack } from '@/types';

export const usePlayerStore = defineStore('player', () => {
  const isOpen = ref(false);
  const animeTitle = ref('');
  const animeUrl = ref('');
  const source = ref('french-manga');
  const currentEpisode = ref<Episode | null>(null);
  const episodes = ref<Episode[]>([]);

  const videoUrl = ref<string | null>(null);
  const subtitles = ref<SubtitleTrack[]>([]);
  const selectedSubtitle = ref<string | null>(null);
  const isDownloaded = ref(false);
  const availableQualities = ref<Record<string, string>>({});
  const availableServers = ref<string[]>([]);
  const selectedQuality = ref('HD');
  const selectedServer = ref('auto');
  const serverType = ref('En ligne');
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  let requestVersion = 0;

  const hasNext = computed(() => {
    if (!currentEpisode.value || !episodes.value.length) return false;
    const idx = episodes.value.findIndex((e) => currentEpisode.value !== null && episodeKey(e) === episodeKey(currentEpisode.value));
    return idx >= 0 && idx < episodes.value.length - 1;
  });

  const hasPrev = computed(() => {
    if (!currentEpisode.value || !episodes.value.length) return false;
    const idx = episodes.value.findIndex((e) => currentEpisode.value !== null && episodeKey(e) === episodeKey(currentEpisode.value));
    return idx > 0;
  });

  async function resolveStream() {
    if (!currentEpisode.value) return;
    const request = ++requestVersion;
    const targetUrl = currentEpisode.value.playerUrl || currentEpisode.value.downloadPageUrl;
    if (!targetUrl) {
      error.value = "Aucun lien de streaming disponible pour cet épisode.";
      return;
    }

    isLoading.value = true;
    error.value = null;
    videoUrl.value = null;

    try {
      const res = await api.resolveVideoStream({
        animeName: animeTitle.value,
        episodeNumber: currentEpisode.value.number,
        episodeUrl: targetUrl,
        animeUrl: animeUrl.value,
        version: currentEpisode.value.version || '',
        source: source.value,
        server: selectedServer.value !== 'auto' ? selectedServer.value : undefined,
        quality: selectedQuality.value !== 'auto' ? selectedQuality.value : undefined,
      });
      if (request !== requestVersion) return;

      const finalUrl = res.streamUrl || res.videoUrl;
      if (res && finalUrl) {
        videoUrl.value = finalUrl;
        subtitles.value = res.subtitles || [];
        selectedSubtitle.value = subtitles.value.length > 0 ? subtitles.value[0].src : null;
        isDownloaded.value = Boolean(res.isDownloaded);

        const qMap = res.qualities || res.videoQualities || {};
        availableQualities.value = qMap;

        if (res.availableServers) availableServers.value = res.availableServers;
        if (res.selectedQuality) selectedQuality.value = res.selectedQuality;
        if (res.serverType) {
          serverType.value = res.serverType;
          if (selectedServer.value === 'auto') {
            selectedServer.value = res.serverType;
          }
        }
      } else {
        error.value = res.error || "Impossible d'extraire la vidéo directe pour cet hébergeur.";
      }
    } catch (e: any) {
      if (request !== requestVersion) return;
      error.value = e.message || 'Erreur lors de la résolution du flux vidéo.';
    } finally {
      if (request === requestVersion) isLoading.value = false;
    }
  }

  async function openPlayer(
    title: string,
    url: string,
    src: string,
    episode: Episode,
    allEps: Episode[] = []
  ) {
    animeTitle.value = title;
    animeUrl.value = url;
    source.value = src;
    currentEpisode.value = episode;
    episodes.value = allEps.filter((e) => (e.version || '') === (episode.version || ''));
    isOpen.value = true;
    selectedServer.value = 'auto';
    selectedQuality.value = 'HD';
    subtitles.value = [];
    selectedSubtitle.value = null;
    await resolveStream();
  }

  function closePlayer() {
    ++requestVersion;
    isOpen.value = false;
    videoUrl.value = null;
    currentEpisode.value = null;
    error.value = null;
    subtitles.value = [];
    selectedSubtitle.value = null;
    isLoading.value = false;
  }

  async function playNext() {
    if (!hasNext.value) return;
    const idx = episodes.value.findIndex((e) => currentEpisode.value !== null && episodeKey(e) === episodeKey(currentEpisode.value));
    if (idx >= 0 && idx < episodes.value.length - 1) {
      currentEpisode.value = episodes.value[idx + 1];
      await resolveStream();
    }
  }

  async function playPrev() {
    if (!hasPrev.value) return;
    const idx = episodes.value.findIndex((e) => currentEpisode.value !== null && episodeKey(e) === episodeKey(currentEpisode.value));
    if (idx > 0) {
      currentEpisode.value = episodes.value[idx - 1];
      await resolveStream();
    }
  }

  async function changeServer(srv: string) {
    selectedServer.value = srv;
    await resolveStream();
  }

  async function changeQuality(q: string) {
    selectedQuality.value = q;
    if (availableQualities.value && availableQualities.value[q]) {
      videoUrl.value = availableQualities.value[q];
    } else {
      await resolveStream();
    }
  }

  function changeSubtitle(src: string | null) {
    selectedSubtitle.value = src;
  }

  async function playLocalFile(taskId: string | number, title: string, epNum: number | string, fileName?: string) {
    const request = ++requestVersion;
    animeTitle.value = title;
    animeUrl.value = '';
    source.value = 'local';
    currentEpisode.value = {
      number: epNum,
      title: fileName || `Épisode ${epNum}`,
      isDownloaded: true,
    };
    episodes.value = [];
    isOpen.value = true;
    isLoading.value = false;
    error.value = null;
    isDownloaded.value = true;
    videoUrl.value = `/api/media/stream/${encodeURIComponent(taskId)}`;
    availableQualities.value = {};
    availableServers.value = [];
    serverType.value = 'Local (Disque)';
    selectedServer.value = 'auto';
    selectedQuality.value = 'HD';
    subtitles.value = [];
    selectedSubtitle.value = null;
    try {
      const tracks = await api.getLocalSubtitles(taskId);
      if (request !== requestVersion) return;
      subtitles.value = tracks;
      selectedSubtitle.value = tracks[0]?.src || null;
    } catch {
      // Optional captions must never prevent the local video from playing.
    }
  }

  return {
    isOpen,
    animeTitle,
    animeUrl,
    source,
    currentEpisode,
    episodes,
    videoUrl,
    subtitles,
    selectedSubtitle,
    isDownloaded,
    availableQualities,
    availableServers,
    selectedQuality,
    selectedServer,
    serverType,
    isLoading,
    error,
    hasNext,
    hasPrev,
    openPlayer,
    playLocalFile,
    closePlayer,
    playNext,
    playPrev,
    changeServer,
    changeQuality,
    changeSubtitle,
    resolveStream,
  };
});
