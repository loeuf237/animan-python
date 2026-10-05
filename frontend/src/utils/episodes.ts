import type { Episode } from '@/types';

export function episodeKey(ep: Episode): string {
  return JSON.stringify([String(ep.number), ep.version || '', ep.downloadPageUrl || ep.playerUrl || '']);
}

export function episodeFileName(title: string, ep: Episode): string {
  return `${title} - Episode ${ep.number}${ep.version ? ` [${ep.version}]` : ''}.mp4`;
}
