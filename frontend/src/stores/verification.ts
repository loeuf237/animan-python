import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api, ApiError } from '@/api/client';
import type { SourceChallenge } from '@/types';

export function challengeFromError(error: unknown): SourceChallenge | null {
  if (error instanceof ApiError && error.data?.code === 'verification_required') return error.data;
  return null;
}

export const useVerificationStore = defineStore('verification', () => {
  const sessions = ref<{domain: string; verificationRequired: boolean; usesProxy: boolean}[]>([]);
  const browsers = ref<{name: string}[]>([]);
  const webviewAvailable = ref(false);
  const browser = ref('');
  const job = ref<{id: string; domain: string} | null>(null);
  const busy = ref(false);
  const error = ref('');
  const notice = ref('');
  const pending = new Map<string, {domains: Set<string>; retry: () => Promise<void>}>();
  let refreshing: Promise<void> | null = null;

  function waitForVerification(key: string, challenges: Pick<SourceChallenge, 'domain'>[], retry: () => Promise<void>) {
    if (challenges.length) pending.set(key, {domains: new Set(challenges.map(c => c.domain)), retry});
    else pending.delete(key);
    if (challenges.length) void refresh();
  }
  function clearPending(key: string) { pending.delete(key); }
  async function refresh() {
    if (refreshing) return refreshing;
    refreshing = (async () => {
      try {
        const result = await api.getNetworkSessions();
        sessions.value = result.sessions;
        browsers.value = result.browsers;
        webviewAvailable.value = result.webviewAvailable;
        if (!browsers.value.some(b => b.name === browser.value)) browser.value = browsers.value[0]?.name || '';
      } catch { /* Retry on the next poll if the server is restarting. */ }
    })();
    try { await refreshing; } finally { refreshing = null; }
  }
  async function start(domain: string, mode = 'browser') {
    if (busy.value || job.value) return;
    busy.value = true; error.value = ''; notice.value = '';
    try { job.value = await api.startNetworkVerification(domain, browser.value, mode); }
    catch (exc) { error.value = exc instanceof Error ? exc.message : 'Impossible d’ouvrir la vérification.'; }
    finally { busy.value = false; }
  }
  async function complete() {
    if (!job.value || busy.value) return;
    busy.value = true; error.value = '';
    try {
      const result = await api.completeNetworkVerification(job.value.id);
      job.value = null;
      const retries = [...pending.entries()].filter(([, request]) => request.domains.has(result.domain));
      for (const [key] of retries) pending.delete(key);
      await Promise.allSettled(retries.map(([, request]) => request.retry()));
      notice.value = retries.length ? 'Accès vérifié. La recherche ou le catalogue a été actualisé.' : `Accès vérifié. ${result.resumed} téléchargement(s) repris.`;
      await refresh();
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : 'Le site demande encore une vérification.';
      if (exc instanceof ApiError && exc.status === 400 && /expir|introuvable|fermé/.test(exc.message)) job.value = null;
    } finally { busy.value = false; }
  }
  async function cancel() {
    if (!job.value || busy.value) return;
    busy.value = true;
    try { await api.cancelNetworkVerification(job.value.id); job.value = null; error.value = ''; }
    catch (exc) { error.value = exc instanceof Error ? exc.message : 'Impossible de fermer la vérification.'; }
    finally { busy.value = false; }
  }
  return {sessions, browsers, browser, job, busy, error, notice, webviewAvailable,
          waitForVerification, clearPending, refresh, start, complete, cancel};
});
