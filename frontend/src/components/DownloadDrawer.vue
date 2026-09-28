<template>
  <div v-if="downloadStore.isDrawerOpen" class="drawer-overlay" @click="downloadStore.toggleDrawer">
    <div class="drawer-panel glass-panel" @click.stop>
      <!-- Header -->
      <div class="drawer-header">
        <div class="header-left">
          <h2>Téléchargements</h2>
          <span class="sse-status" :class="{ connected: downloadStore.isConnected }">
            {{ downloadStore.isConnected ? '● En direct' : '○ Polling' }}
          </span>
        </div>
        <button class="btn-icon" @click="downloadStore.toggleDrawer">✕</button>
      </div>

      <!-- Stats Bar -->
      <div class="drawer-stats">
        <div class="stat-item">
          <span class="stat-label">En cours</span>
          <span class="stat-value">{{ downloadStore.stats.activeCount }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Vitesse</span>
          <span class="stat-value">{{ formatSpeed(downloadStore.stats.totalSpeed) }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">Terminés</span>
          <span class="stat-value">{{ downloadStore.stats.completedCount }}</span>
        </div>
      </div>

      <!-- Action Toolbar -->
      <div class="drawer-toolbar">
        <button
          v-if="downloadStore.stats.completedCount > 0"
          class="btn-secondary btn-sm"
          @click="downloadStore.cleanCompleted"
        >
          Nettoyer terminés
        </button>
        <button class="btn-secondary btn-sm" @click="downloadStore.fetchTasks">
          Actualiser
        </button>
      </div>

      <!-- Tasks List -->
      <div class="tasks-container">
        <div v-if="downloadStore.tasks.length === 0" class="empty-state">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <p>Aucun téléchargement en cours</p>
        </div>

        <div
          v-for="task in downloadStore.tasks"
          :key="task.id"
          class="task-card"
          :class="`status-${task.status}`"
        >
          <div class="task-top">
            <div class="task-info">
              <span class="task-anime">{{ task.animeName }}</span>
              <span class="task-ep">Épisode {{ task.episodeNumber }}</span>
            </div>
            <span class="badge" :class="getStatusBadgeClass(task.status)">
              {{ formatStatusLabel(task.status) }}
            </span>
          </div>

          <!-- Progress bar -->
          <div class="progress-track">
            <div
              class="progress-fill"
              :style="{ width: `${task.progress || 0}%` }"
              :class="{ downloading: task.status === 'downloading' }"
            ></div>
          </div>

          <div class="task-bottom">
            <div class="task-details">
              <span>{{ (task.progress || 0).toFixed(1) }}%</span>
              <span v-if="task.status === 'downloading'">
                • {{ formatSpeed(task.downloadSpeed) }} • ETA {{ formatEta(task.eta) }}
              </span>
              <span v-else-if="(task.totalBytes || 0) > 0">
                • {{ formatBytes(task.totalBytes) }}
              </span>
            </div>

            <!-- Task controls -->
            <div class="task-actions">
              <button
                v-if="task.status === 'downloading'"
                class="btn-icon-sm"
                title="Mettre en pause"
                @click="downloadStore.pauseDownload(task.id)"
              >
                ⏸
              </button>
              <button
                v-if="task.status === 'paused'"
                class="btn-icon-sm"
                title="Reprendre"
                @click="downloadStore.resumeDownload(task.id)"
              >
                ▶
              </button>
              <button
                v-if="task.status === 'error' || task.status === 'failed'"
                class="btn-icon-sm"
                title="Réessayer"
                @click="downloadStore.retryDownload(task.id)"
              >
                🔄
              </button>
              <button
                class="btn-icon-sm btn-icon-danger"
                title="Supprimer / Annuler"
                @click="downloadStore.cancelDownload(task.id)"
              >
                ✕
              </button>
            </div>
          </div>

          <div v-if="task.error" class="task-error-msg">
            {{ task.error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useDownloadStore } from '@/stores/downloads';

const downloadStore = useDownloadStore();

function formatSpeed(bytesPerSec?: number | null): string {
  if (!bytesPerSec || bytesPerSec <= 0) return '0 KB/s';
  const mb = bytesPerSec / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(2)} MB/s`;
  const kb = bytesPerSec / 1024;
  return `${kb.toFixed(1)} KB/s`;
}

function formatBytes(bytes?: number | null): string {
  if (!bytes) return '0 MB';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb.toFixed(1)} MB`;
}

function formatEta(seconds?: number | null): string {
  if (!seconds || seconds <= 0 || seconds > 86400) return '--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m > 60) {
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  }
  return `${m}m ${s}s`;
}

function getStatusBadgeClass(status: string) {
  const s = (status || '').toLowerCase();
  switch (s) {
    case 'completed': return 'badge-success';
    case 'downloading': return 'badge-source';
    case 'error':
    case 'failed': return 'badge-warning';
    case 'paused': return 'badge-warning';
    default: return '';
  }
}

function formatStatusLabel(status: string) {
  const s = (status || '').toLowerCase();
  switch (s) {
    case 'downloading': return 'En cours';
    case 'queued':
    case 'pending': return 'En attente';
    case 'scheduled': return 'Planifié';
    case 'paused': return 'En pause';
    case 'completed': return 'Terminé';
    case 'error':
    case 'failed': return 'Échec';
    case 'cancelled': return 'Annulé';
    default: return status;
  }
}
</script>

<style scoped>
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 200;
  display: flex;
  justify-content: flex-end;
  animation: fadeIn 0.2s ease;
}

.drawer-panel {
  width: 440px;
  max-width: 90vw;
  height: 100vh;
  border-radius: 0;
  border-left: 1px solid var(--border-highlight);
  background: rgba(14, 18, 30, 0.95);
  backdrop-filter: blur(24px);
  display: flex;
  flex-direction: column;
  animation: slideLeft 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideLeft {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.drawer-header {
  padding: 20px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-subtle);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sse-status {
  font-size: 0.75rem;
  color: var(--text-dim);
  font-weight: 600;
}
.sse-status.connected {
  color: var(--color-success);
}

.drawer-stats {
  display: flex;
  padding: 16px 24px;
  gap: 16px;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid var(--border-subtle);
}

.stat-item {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.stat-value {
  font-size: 1.1rem;
  font-weight: 700;
  font-family: 'Outfit', sans-serif;
  color: var(--accent-secondary);
}

.drawer-toolbar {
  padding: 10px 24px;
  display: flex;
  gap: 10px;
  border-bottom: 1px solid var(--border-subtle);
}

.btn-sm {
  padding: 6px 12px;
  font-size: 0.8rem;
}

.tasks-container {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 60%;
  color: var(--text-dim);
  gap: 12px;
}

.task-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.task-info {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.task-anime {
  font-weight: 600;
  font-size: 0.9rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 250px;
}

.task-ep {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.progress-track {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent-gradient);
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
}

.progress-fill.downloading {
  box-shadow: 0 0 10px rgba(99, 102, 241, 0.8);
}

.task-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8rem;
  color: var(--text-muted);
}

.task-actions {
  display: flex;
  gap: 6px;
}

.btn-icon-sm {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-main);
  cursor: pointer;
  font-size: 0.8rem;
}

.btn-icon-sm:hover {
  background: rgba(255, 255, 255, 0.16);
}

.btn-icon-danger:hover {
  background: var(--color-danger);
  color: #fff;
}

.task-error-msg {
  font-size: 0.75rem;
  color: var(--color-danger);
}
</style>
