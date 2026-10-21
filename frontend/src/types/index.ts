export interface SourceChallenge { domain: string; url?: string; source?: string; code: string; error: string }
export interface SearchResponse { results: AnimeResult[]; challenges: SourceChallenge[]; errors: {source: string; message: string; url?: string; domain?: string}[] }
export interface CatalogueSource {
  id: string; name: string; type: string; lang: string; baseUrl: string; isEnabled: boolean;
  views: {id: string; label: string}[]; multiTags: boolean;
}
export interface CatalogueFilters {
  tags: {id: string; label: string; group: string}[];
  orders: {id: string; label: string}[];
}
export interface CataloguePage { source: string; results: AnimeResult[]; nextCursor: string | null; queryScope: string }

export interface AnimeResult {
  title: string;
  url: string;
  imageUrl: string;
  source: string;
  type?: string | null;
  status?: string | null;
  rating?: number | null;
  latestEpisode?: string | null;
  episodeInfo?: string | null;
  version?: string | null;
  genres?: string[];
  synopsis?: string | null;
}

export interface SubtitleTrack {
  kind?: string;
  label: string;
  srclang?: string;
  src: string;
  default?: boolean;
}

export interface Episode {
  number: string | number;
  title: string;
  downloadPageUrl?: string | null;
  playerUrl?: string | null;
  directDownloadUrl?: string | null;
  subtitleUrl?: string | null;
  subtitlesEnabled?: boolean;
  version?: string | null;
  synopsis?: string | null;
  thumbnailUrl?: string | null;
  releaseDate?: string | null;
  isDownloaded?: boolean;
  isWatched?: boolean;
  downloadTaskId?: number | string | null;
}

export interface AnimeDetail {
  title: string;
  url: string;
  imageUrl: string;
  source: string;
  synopsis?: string | null;
  genres: string[];
  type?: string | null;
  status?: string | null;
  rating?: number | null;
  backdropUrl?: string | null;
  episodes: Episode[];
  version?: string | null;
  availableVersions?: string[];
}

export interface AnimeDetailResponse {
  success: boolean;
  anime: AnimeDetail;
  source: string;
  isFavorite: boolean;
  autoDownload: boolean;
  downloadedEpisodes: (string | number)[];
  watchedEpisodes: (string | number)[];
  totalEpisodes: number;
  downloadedCount: number;
  watchedCount: number;
}

export interface DownloadTask {
  exportStatus?: 'NOT_REQUESTED' | 'PENDING' | 'EXPORTING' | 'EXPORTED' | 'EXPORT_FAILED';
  exportUris?: string[];
  exportDestination?: string | null;
  exportError?: string | null;
  exportAttempts?: number;
  exportedAt?: string | null;
  id: number | string;
  animeName: string;
  episodeNumber: number | string;
  fileName: string;
  version?: string;
  phase?: string | null;
  rawStatus?: string;
  filePath?: string | null;
  savePath?: string | null;
  fileUrl?: string | null;
  status: 'queued' | 'downloading' | 'paused' | 'completed' | 'error' | 'cancelled' | string;
  progress: number;
  bytesDownloaded?: number;
  downloadedBytes?: number;
  totalBytes?: number;
  downloadedSize?: string;
  totalSize?: string;
  downloadSpeed?: number;
  speed?: string;
  speedBytes?: number;
  eta?: number;
  error?: string | null;
  source?: string | null;
  selectedQuality?: string | null;
  selectedServer?: string | null;
  createdAt?: string | null;
  completedAt?: string | null;
  verificationDomain?: string | null;
  verificationUrl?: string | null;
  verificationStatus?: 'VALID' | 'MISSING' | 'CORRUPTED' | 'EMPTY' | 'UNVERIFIED' | string;
  verificationError?: string | null;
  videoDuration?: number | null;
  formattedDuration?: string | null;
  maxSpeedLimit?: number | null;
  scheduledStartTime?: string | null;
  imageUrl?: string | null;
}

export interface DownloadSettings {
  maxConcurrentDownloads: number;
  globalSpeedLimit: number;
  plexOrganization?: boolean;
  selectedUserAgent?: string;
  voiranimeDefaultServer?: string;
}

export interface DownloadStats {
  activeCount: number;
  queuedCount: number;
  completedCount: number;
  errorCount: number;
  totalSpeed: number;
}

export interface AutoDownloadOptions {
  autoDownloadVersion?: string;
  autoDownloadSubtitles?: boolean;
  autoDownloadServer?: string | null;
  autoDownloadQuality?: string | null;
}

export interface FavoriteItem extends AutoDownloadOptions {
  id?: number;
  url: string;
  title: string;
  imageUrl: string;
  source: string;
  autoDownload: boolean;
  autoDownloadError?: string | null;
  lastEpisodeChecked?: string | null;
  newEpisodesCount?: number;
  createdAt?: string;
}

export interface HistoryItem {
  id?: number | string;
  animeUrl?: string;
  animeName?: string;
  animeTitle?: string;
  animeImageUrl?: string;
  source?: string;
  episodeNumber?: string | number;
  lastPosition?: number;
  duration?: number;
  updatedAt?: string;
  createdAt?: string;
  status?: string;
}

export interface ExtensionSource {
  health?: import('./api').ExtensionHealth[];
  recipe_revision?: number;
  supportsLatest?: boolean;
  recipe_json?: string | null;
  id: number | string;
  pkg: string;
  name: string;
  lang?: string;
  version?: string;
  enabled?: boolean;
  is_enabled?: boolean;
  iconUrl?: string | null;
  icon_url?: string | null;
  baseUrl?: string | null;
  base_url?: string | null;
  isInstalled?: boolean;
}

export interface HomeFeedResponse {
  challenges?: SourceChallenge[];
  errors?: {source: string; message: string; url?: string; domain?: string}[];
  success: boolean;
  latestReleases?: Record<string, AnimeResult[]>;
  latestFrenchManga?: AnimeResult[];
  latestVoirAnime?: AnimeResult[];
  latestAnimePahe?: AnimeResult[];
  extensionsReleases?: Record<string, { name: string; releases: AnimeResult[] }>;
  favorites: FavoriteItem[];
  recentHistory: HistoryItem[];
  enabledExtensions: ExtensionSource[];
}

export interface VideoStreamInfo {
  success?: boolean;
  streamUrl?: string;
  videoUrl?: string;
  serverType?: string;
  availableServers?: string[];
  qualities?: Record<string, string>;
  videoQualities?: Record<string, string>;
  selectedQuality?: string;
  title?: string;
  subtitles?: SubtitleTrack[];
  isDownloaded?: boolean;
  filePath?: string;
  sourceType?: string;
  error?: string;
  referer?: string;
  headers?: Record<string, string>;
}
