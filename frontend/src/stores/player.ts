import type { PlaybackState, PlaybackOpen, PlaybackTrack, PlaybackCheckpoint } from '@/types/api';
import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { api } from '@/api/client';
import { episodeKey } from '@/utils/episodes';
import type { Episode, SubtitleTrack } from '@/types';

export function playbackTrackKey(track: {kind?: string; srclang?: string; label?: string}) {
  return JSON.stringify([track.kind || 'subtitles',track.srclang || '',track.label || '']).slice(0,500);
}

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

  const mediaEpoch=ref(0);
  const playback = ref<PlaybackState | null>(null);
  const resumePosition = ref<number | null>(null);
  const progressNotice = ref('');
  const audioTracks = ref<PlaybackTrack[]>([]);
  const selectedAudio = ref<string | null>(null);
  let clock: {positionSeconds: number; durationSeconds: number} | null = null;
  let lastSave = -Infinity, sequence = 0, lastFingerprint = '';

  function recordTime(position: number, duration: number) {
    if (!Number.isFinite(position) || !Number.isFinite(duration) || duration <= 0 || position < 0) return;
    clock = {positionSeconds: Math.min(position,duration,604800), durationSeconds: Math.min(duration,604800)};
  }
  function selection() {
    const subtitle = subtitles.value.find(track => track.src === selectedSubtitle.value);
    return {quality:selectedQuality.value,server:selectedServer.value,
            subtitle:subtitle ? playbackTrackKey(subtitle) : null,audio:selectedAudio.value};
  }
  function savePlayback(final = false, ended = false): Promise<void> {
    const session = playback.value;
    if (!session || !clock || !api.savePlaybackCheckpoint) return Promise.resolve();
    const fingerprint = JSON.stringify([session.sessionId,clock,selection(),ended]);
    if (fingerprint === lastFingerprint || (!final && Date.now()-lastSave < 5000)) return Promise.resolve();
    lastSave=Date.now();lastFingerprint=fingerprint;
    const body: PlaybackCheckpoint={sessionId:session.sessionId,sequence:++sequence,...clock,selection:selection(),final,ended};
    return api.savePlaybackCheckpoint(body).then(result => {
      if (playback.value?.sessionId === session.sessionId) progressNotice.value=result?.reason==='superseded'
        ? 'Une autre fenêtre a repris la lecture de cet épisode.' : '';
    }).catch(() => {
      if (playback.value?.sessionId === session.sessionId) {
        progressNotice.value='La progression n’a pas pu être enregistrée.';
        lastFingerprint='';
      }
    });
  }
  async function loadPlayback(body: PlaybackOpen, request: number) {
    ++mediaEpoch.value;
    playback.value=null;resumePosition.value=null;clock=null;sequence=0;lastSave=-Infinity;lastFingerprint='';
    progressNotice.value='';audioTracks.value=[];selectedAudio.value=null;
    if (!api.openPlaybackSession) return;
    const controller=new AbortController();
    const timer=setTimeout(() => controller.abort(),2000);
    try {
      const result=await api.openPlaybackSession(body,controller.signal);
      if (request!==requestVersion) return;
      playback.value=result;resumePosition.value=result.positionSeconds;
      selectedQuality.value=result.selection.quality;selectedServer.value=result.selection.server;
      selectedAudio.value=result.selection.audio;
    } catch {
      if (request===requestVersion) progressNotice.value='La reprise de lecture est momentanément indisponible.';
    } finally {clearTimeout(timer);}
  }
  function chooseSubtitles() {
    const choice=playback.value?.selection.subtitle;
    selectedSubtitle.value=choice === null ? null : choice && choice!=='auto'
      ? subtitles.value.find(track=>playbackTrackKey(track)===choice)?.src || null : subtitles.value[0]?.src || null;
  }

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
        chooseSubtitles();
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
    void savePlayback(true);
    ++mediaEpoch.value;
    videoUrl.value=null;
    const openRequest=++requestVersion;
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
    await loadPlayback({source:src,animeUrl:url,animeName:title,episodeNumber:Number(episode.number),version:episode.version || ''},openRequest);
    if (openRequest===requestVersion) await resolveStream();
  }

  function closePlayer() {
    void savePlayback(true);
    ++mediaEpoch.value;
    playback.value=null;resumePosition.value=null;clock=null;
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
      void savePlayback(true);
      ++mediaEpoch.value;videoUrl.value=null;
      const request=++requestVersion;
      currentEpisode.value = episodes.value[idx + 1];
      const episode=currentEpisode.value!;
      await loadPlayback({source:source.value,animeUrl:animeUrl.value,animeName:animeTitle.value,episodeNumber:Number(episode.number),version:episode.version || ''},request);
      if (request!==requestVersion) return;
      await resolveStream();
    }
  }

  async function playPrev() {
    if (!hasPrev.value) return;
    const idx = episodes.value.findIndex((e) => currentEpisode.value !== null && episodeKey(e) === episodeKey(currentEpisode.value));
    if (idx > 0) {
      void savePlayback(true);
      ++mediaEpoch.value;videoUrl.value=null;
      const request=++requestVersion;
      currentEpisode.value = episodes.value[idx - 1];
      const episode=currentEpisode.value!;
      await loadPlayback({source:source.value,animeUrl:animeUrl.value,animeName:animeTitle.value,episodeNumber:Number(episode.number),version:episode.version || ''},request);
      if (request!==requestVersion) return;
      await resolveStream();
    }
  }

  async function changeServer(srv: string) {
    void savePlayback(true);
    resumePosition.value=clock?.positionSeconds ?? null;
    selectedServer.value = srv;
    await resolveStream();
  }

  async function changeQuality(q: string) {
    void savePlayback(true);
    resumePosition.value=clock?.positionSeconds ?? null;
    selectedQuality.value = q;
    if (availableQualities.value && availableQualities.value[q]) {
      videoUrl.value = availableQualities.value[q];
    } else {
      await resolveStream();
    }
  }

  function changeSubtitle(src: string | null) {
    selectedSubtitle.value = src;
    if (playback.value) playback.value.selection.subtitle=selection().subtitle;
    void savePlayback(true);
  }

  async function playLocalFile(taskId: string | number, title: string, epNum: number | string, fileName?: string) {
    void savePlayback(true);
    ++mediaEpoch.value;
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
    await loadPlayback({taskId:String(taskId)},request);
    if (request!==requestVersion) return;
    if (playback.value) {
      animeUrl.value=playback.value.animeUrl;
      source.value=playback.value.source;
      if (currentEpisode.value) currentEpisode.value.version=playback.value.version;
    }
    try {
      const tracks = await api.getLocalSubtitles(taskId);
      if (request !== requestVersion) return;
      subtitles.value = tracks;
      chooseSubtitles();
    } catch {
      // Optional captions must never prevent the local video from playing.
    }
  }

  return {
    mediaEpoch,playback,resumePosition,progressNotice,audioTracks,selectedAudio,recordTime,savePlayback,
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
