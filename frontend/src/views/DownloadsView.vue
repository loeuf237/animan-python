<template>
  <div class="downloads-container fade-in">
    <!-- Header avec Statistiques -->
    <section class="dashboard-header">
      <div>
        <h1 class="page-title">Gestionnaire des Téléchargements</h1>
        <p class="page-sub">Suivez et pilotez vos flux d'épisodes en tâche de fond avec contrôle d'intégrité.</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <strong>{{ downloadStore.stats.activeCount }}</strong>
          <span>Actifs</span>
        </div>
        <div class="stat-card stat-blue">
          <strong>{{ downloadStore.stats.queuedCount }}</strong>
          <span>En attente</span>
        </div>
        <div class="stat-card stat-green">
          <strong>{{ formatSpeed(downloadStore.stats.totalSpeed) }}</strong>
          <span>Vitesse globale</span>
          <i class="mini-spark"></i>
        </div>
        <div
          v-if="errorTasksCount > 0"
          class="stat-card stat-red clickable"
          title="Afficher les téléchargements en échec"
          @click="tab = 'errors'"
        >
          <strong>{{ errorTasksCount }}</strong>
          <span>En échec</span>
        </div>
      </div>
    </section>

    <!-- Toolbar Principale -->
    <section class="download-toolbar">
      <div class="download-tabs">
        <button
          class="tab-btn"
          :class="{ active: tab === 'queue' }"
          type="button"
          @click="tab = 'queue'"
        >
          En cours & Attente
          <span class="tab-badge badge-queue">{{ activeAndQueuedCount }}</span>
        </button>
        <button
          class="tab-btn"
          :class="{ active: tab === 'done' }"
          type="button"
          @click="tab = 'done'"
        >
          Terminés
          <span class="tab-badge badge-done">{{ completedCount }}</span>
        </button>
        <button
          class="tab-btn"
          :class="{ active: tab === 'errors' }"
          type="button"
          @click="tab = 'errors'"
        >
          Erreurs
          <span class="tab-badge badge-error">{{ errorTasksCount }}</span>
        </button>
        <button
          class="tab-btn"
          :class="{ active: tab === 'all' }"
          type="button"
          @click="tab = 'all'"
        >
          Tous
          <span class="tab-badge">{{ downloadStore.tasks.length }}</span>
        </button>
      </div>

      <div class="download-actions">
        <!-- Actions globales selon l'onglet -->
        <button
          v-if="tab === 'queue' || tab === 'all'"
          class="btn btn-sm"
          type="button"
          title="Mettre en pause tous les téléchargements en cours"
          @click="downloadStore.pauseAll"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 5v14M16 5v14"/></svg>
          Tout suspendre
        </button>

        <button
          v-if="tab === 'queue' || tab === 'all'"
          class="btn btn-success btn-sm"
          type="button"
          title="Reprendre tous les téléchargements en pause"
          @click="downloadStore.resumeAll"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 4v16l13-8Z"/></svg>
          Tout reprendre
        </button>

        <button
          v-if="tab === 'done'"
          class="btn btn-sm"
          type="button"
          :disabled="isVerifyingAll"
          title="Vérifier la validité de tous les fichiers vidéo téléchargés"
          @click="verifyAll"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
          {{ isVerifyingAll ? 'Vérification...' : 'Vérifier l\'intégrité' }}
        </button>

        <button
          v-if="tab === 'errors'"
          class="btn btn-warning btn-sm"
          type="button"
          title="Relancer tous les téléchargements en échec"
          @click="retryAllErrors"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
          Tout relancer
        </button>

        <button
          v-if="tab === 'queue' || tab === 'all'"
          class="btn btn-danger-outline btn-sm"
          type="button"
          title="Annuler tous les téléchargements"
          @click="confirmCancelAll"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
          Tout annuler
        </button>

        <button
          v-if="tab === 'done' || tab === 'errors'"
          class="btn btn-danger-outline btn-sm"
          type="button"
          title="Nettoyer les tâches de cette vue"
          @click="downloadStore.cleanCompleted"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/></svg>
          Nettoyer
        </button>

        <!-- Bouton Accordéon Réglages Rapides -->
        <button
          class="btn btn-icon-round"
          :class="{ active: isSettingsOpen }"
          type="button"
          title="Paramètres rapides de débit et téléchargement"
          @click="isSettingsOpen = !isSettingsOpen"
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </button>
      </div>
    </section>

    <!-- Panneau Déroulant des Réglages Rapides (In-Page Accordion) -->
    <Transition name="expand">
      <section v-if="isSettingsOpen" class="quick-settings-panel">
        <div class="quick-settings-header">
          <div class="quick-settings-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3H9.6L9.2 6.1a7 7 0 0 0-1.8 1L5 6.1l-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.4 3.1h4.8l.4-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"/></svg>
            <span>Réglages Rapides des Téléchargements</span>
          </div>
          <button class="btn btn-sm btn-primary" :disabled="isSavingSettings" @click="saveSettings">
            {{ isSavingSettings ? 'Enregistrement...' : 'Appliquer' }}
          </button>
        </div>

        <div class="quick-settings-grid">
          <!-- Téléchargements simultanés -->
          <div class="qs-item">
            <label class="qs-label">Téléchargements simultanés</label>
            <div class="qs-control">
              <input
                v-model.number="quickSettings.maxConcurrentDownloads"
                type="number"
                class="input-premium qs-number-input"
                min="1"
                max="10"
              />
              <span class="qs-hint">Flux max en parallèle (1-10)</span>
            </div>
          </div>

          <!-- Limite de débit globale -->
          <div class="qs-item qs-item-wide">
            <label class="qs-label">Plafond de vitesse globale (Ko/s)</label>
            <div class="qs-control-col">
              <div class="qs-input-row">
                <input
                  v-model.number="quickSettings.globalSpeedLimitKb"
                  type="number"
                  class="input-premium qs-number-input"
                  placeholder="Illimité"
                  min="0"
                />
                <span class="qs-unit">Ko/s {{ quickSettings.globalSpeedLimitKb ? `(~${(quickSettings.globalSpeedLimitKb / 1024).toFixed(1)} Mo/s)` : '(Illimité)' }}</span>
              </div>
              <!-- Presets rapides en 1 clic -->
              <div class="speed-presets">
                <button
                  type="button"
                  class="preset-chip"
                  :class="{ active: !quickSettings.globalSpeedLimitKb || quickSettings.globalSpeedLimitKb === 0 }"
                  @click="quickSettings.globalSpeedLimitKb = 0"
                >
                  Illimité
                </button>
                <button
                  type="button"
                  class="preset-chip"
                  :class="{ active: quickSettings.globalSpeedLimitKb === 1024 }"
                  @click="quickSettings.globalSpeedLimitKb = 1024"
                >
                  1 Mo/s
                </button>
                <button
                  type="button"
                  class="preset-chip"
                  :class="{ active: quickSettings.globalSpeedLimitKb === 3072 }"
                  @click="quickSettings.globalSpeedLimitKb = 3072"
                >
                  3 Mo/s
                </button>
                <button
                  type="button"
                  class="preset-chip"
                  :class="{ active: quickSettings.globalSpeedLimitKb === 5120 }"
                  @click="quickSettings.globalSpeedLimitKb = 5120"
                >
                  5 Mo/s
                </button>
                <button
                  type="button"
                  class="preset-chip"
                  :class="{ active: quickSettings.globalSpeedLimitKb === 10240 }"
                  @click="quickSettings.globalSpeedLimitKb = 10240"
                >
                  10 Mo/s
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </Transition>

    <!-- Indication de réorganisation si file d'attente active -->
    <div v-if="tab === 'queue' && queuedTasks.length > 1" class="queue-reorder-hint">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
      <span>Glissez-déposez les tâches en attente avec la poignée <strong>::</strong> ou utilisez les boutons pour réorganiser l'ordre de priorité.</span>
    </div>

    <!-- Empty State -->
    <div v-if="filteredTasks.length === 0" class="empty-state">
      <div class="empty-icon-circle">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/></svg>
      </div>
      <h3>{{ emptyStateTitle }}</h3>
      <p>{{ emptyStateDescription }}</p>
      <router-link to="/" class="btn btn-primary" style="margin-top: 14px;">
        Rechercher des animés
      </router-link>
    </div>

    <!-- Liste des Tâches -->
    <div v-else class="tasks-table">
      <div
        v-for="task in filteredTasks"
        :key="task.id"
        class="task-row-card"
        :class="[`status-${task.status}`, { 'is-dragging': draggedTaskId === task.id }]"
        :draggable="tab === 'queue' && task.status === 'queued'"
        @dragstart="onDragStart(task, $event)"
        @dragover.prevent="onDragOver(task, $event)"
        @drop="onDrop(task, $event)"
        @dragend="onDragEnd"
      >
        <!-- Poignée Drag & Drop + Index de priorité pour la file d'attente -->
        <div v-if="tab === 'queue' && task.status === 'queued'" class="task-drag-handle" title="Glisser pour réorganiser la priorité">
          <span class="queue-order-badge">{{ getQueueIndex(task.id) }}</span>
          <span class="drag-dots">⋮⋮</span>
        </div>

        <!-- Cover Avatar / Poster de l'animé -->
        <div class="task-cover">
          <img
            v-if="getAnimePoster(task.animeName)"
            :src="getAnimePoster(task.animeName)!"
            :alt="task.animeName"
            class="task-cover-img"
            loading="lazy"
          />
          <div v-else class="task-cover-fallback">
            {{ getInitials(task.animeName) }}
          </div>
        </div>

        <!-- Informations Principales & Progression -->
        <div class="task-col-main">
          <div class="task-title-line">
            <strong class="task-anime-title" :title="task.animeName">{{ task.animeName }}</strong>
            <span class="badge" :class="getStatusBadgeClass(task)">{{ getStatusLabel(task) }}</span>
            <span v-if="task.selectedQuality" class="quality-tag">{{ task.selectedQuality }}</span>
            <span v-if="task.source" class="source-tag">{{ task.source }}</span>
          </div>

          <div class="task-meta-line">
            <span class="task-ep-number">Épisode {{ task.episodeNumber }}</span>
            <span v-if="task.fileName" class="task-filename" :title="task.fileName">• {{ task.fileName }}</span>
            <span v-if="task.scheduledStartTime" class="task-scheduled-time">
              • ⏱ Planifié : {{ formatDateTime(task.scheduledStartTime) }}
            </span>
          </div>

          <!-- Barre de progression intelligente -->
          <div class="progress-bar-container">
            <div
              class="progress-bar-fill"
              :class="{
                active: task.status === 'downloading',
                paused: task.status === 'paused',
                error: task.status === 'error' || task.status === 'failed',
                completed: task.status === 'completed'
              }"
              :style="{ width: `${getVisualProgress(task)}%` }"
            ></div>
          </div>

          <!-- Métriques de téléchargement & Vérification -->
          <div class="task-stats-line">
            <div class="task-stats-left">
              <span>{{ (task.progress || 0).toFixed(1) }}% ({{ formatBytes(task.bytesDownloaded) }} / {{ formatBytes(task.totalBytes) }})</span>
              
              <!-- Badge de vérification d'intégrité -->
              <span
                v-if="task.verificationStatus && task.verificationStatus !== 'UNVERIFIED'"
                class="verif-badge"
                :class="getVerifBadgeClass(task.verificationStatus)"
                :title="task.verificationError || 'Vérification d\'intégrité des flux vidéo et audio'"
              >
                <svg v-if="task.verificationStatus === 'VALID'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
                <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                {{ formatVerifLabel(task) }}
              </span>
            </div>

            <div class="task-stats-right">
              <span v-if="task.status === 'downloading'" class="live-speed">
                {{ formatSpeed(task.downloadSpeed) }}
                <span v-if="task.eta && task.eta > 0" class="live-eta">• ETA {{ formatEta(task.eta) }}</span>
              </span>

              <!-- Badge / Bouton Limite de débit par tâche -->
              <button
                v-if="task.status === 'downloading' || task.status === 'queued' || task.status === 'paused'"
                type="button"
                class="speed-limit-chip"
                :title="task.maxSpeedLimit && task.maxSpeedLimit > 0 ? `Plafond actuel : ${Math.round(task.maxSpeedLimit / 1024)} Ko/s (Cliquer pour modifier)` : 'Définir un plafond de vitesse pour ce téléchargement'"
                @click="openSpeedLimitModal(task)"
              >
                <span>⚡ {{ task.maxSpeedLimit && task.maxSpeedLimit > 0 ? `${Math.round(task.maxSpeedLimit / 1024)} Ko/s` : 'Limiter' }}</span>
              </button>
            </div>
          </div>

          <!-- Alerte explicite si erreur / flux endommagé -->
          <div v-if="task.error || (task.verificationStatus && task.verificationStatus !== 'VALID' && task.verificationStatus !== 'UNVERIFIED')" class="task-error-box">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <span>{{ task.error || task.verificationError || 'Anomalie détectée lors de l\'analyse du conteneur vidéo' }}</span>
          </div>
        </div>

        <!-- Boutons d'Action Contextuels -->
        <div class="task-col-actions">
          <!-- Actif : Pause & Annuler -->
          <template v-if="task.status === 'downloading'">
            <button class="btn btn-sm btn-icon" title="Mettre en pause" @click="downloadStore.pauseDownload(task.id)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 5v14M16 5v14"/></svg>
            </button>
            <button class="btn btn-danger-outline btn-sm btn-icon" title="Annuler le téléchargement" @click="downloadStore.cancelDownload(task.id)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </template>

          <!-- En pause : Reprendre & Annuler -->
          <template v-else-if="task.status === 'paused'">
            <button class="btn btn-success btn-sm btn-icon" title="Reprendre" @click="downloadStore.resumeDownload(task.id)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 4v16l13-8Z"/></svg>
            </button>
            <button class="btn btn-danger-outline btn-sm btn-icon" title="Annuler" @click="downloadStore.cancelDownload(task.id)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </template>

          <!-- En file d'attente : Monter en tête, Prioriser la série, Annuler -->
          <template v-else-if="task.status === 'queued'">
            <button class="btn btn-sm btn-icon" title="Monter en tête de file d'attente" @click="moveTaskToTop(task)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
            </button>
            <button class="btn btn-sm btn-icon" title="Prioriser tous les épisodes de cette série" @click="moveSeriesToTop(task)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
            </button>
            <button class="btn btn-danger-outline btn-sm btn-icon" title="Annuler" @click="downloadStore.cancelDownload(task.id)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </template>

          <!-- Terminé : Lire (Mode Cinéma local), Vérifier l'intégrité, Supprimer -->
          <template v-else-if="task.status === 'completed'">
            <button class="btn btn-primary btn-sm btn-icon" title="Lire la vidéo locale (Mode Cinéma)" @click="playTask(task)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4v16l13-8Z"/></svg>
            </button>
            <button class="btn btn-sm btn-icon" title="Vérifier l'intégrité du fichier MP4" @click="verifySingleTask(task)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
            </button>
            <button
              v-if="task.verificationStatus && task.verificationStatus !== 'VALID' && task.verificationStatus !== 'UNVERIFIED'"
              class="btn btn-warning btn-sm btn-icon"
              title="Fichier corrompu : Re-télécharger proprement"
              @click="redownloadTask(task)"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
            </button>
            <button class="btn btn-danger-outline btn-sm btn-icon" title="Supprimer de la liste" @click="removeTask(task)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </template>

          <!-- Erreur / Annulé : Re-télécharger proprement (Smart Redownload) & Supprimer -->
          <template v-else-if="task.status === 'error' || task.status === 'failed' || task.status === 'cancelled'">
            <button class="btn btn-warning btn-sm" title="Nettoyer le fichier corrompu et relancer un lien direct propre" @click="redownloadTask(task)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
              <span>Réessayer</span>
            </button>
            <button class="btn btn-danger-outline btn-sm btn-icon" title="Supprimer de la liste" @click="removeTask(task)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </template>
        </div>
      </div>
    </div>

    <!-- Modale Réglage Plafond Débit Tâche Individuelle -->
    <Transition name="fade">
      <div v-if="speedModalTask" class="modal-overlay" @click.self="speedModalTask = null">
        <div class="modal-card">
          <div class="modal-header">
            <h3>Plafond de vitesse : {{ speedModalTask.animeName }} (Ep. {{ speedModalTask.episodeNumber }})</h3>
            <button class="btn-icon" @click="speedModalTask = null">✕</button>
          </div>
          <div class="modal-body">
            <p class="modal-sub">Définissez une vitesse maximale spécifique pour ce flux sans brider les autres téléchargements.</p>
            <div class="modal-input-group">
              <input
                v-model.number="taskSpeedLimitInput"
                type="number"
                class="input-premium"
                placeholder="Ex: 500 pour 500 Ko/s (0 = Illimité)"
                min="0"
              />
              <span class="modal-unit">Ko/s</span>
            </div>
            <div class="speed-presets" style="margin-top: 12px;">
              <button type="button" class="preset-chip" @click="taskSpeedLimitInput = 0">Illimité</button>
              <button type="button" class="preset-chip" @click="taskSpeedLimitInput = 500">500 Ko/s</button>
              <button type="button" class="preset-chip" @click="taskSpeedLimitInput = 1024">1 Mo/s</button>
              <button type="button" class="preset-chip" @click="taskSpeedLimitInput = 2048">2 Mo/s</button>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn" @click="speedModalTask = null">Annuler</button>
            <button class="btn btn-primary" @click="applyTaskSpeedLimit">Appliquer</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Toast Notification -->
    <Transition name="fade">
      <div v-if="toastMessage" class="toast" :class="`toast-${toastType}`">
        {{ toastMessage }}
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useDownloadStore } from '@/stores/downloads';
import { useLibraryStore } from '@/stores/library';
import { usePlayerStore } from '@/stores/player';
import type { DownloadTask } from '@/types';

const downloadStore = useDownloadStore();
const libraryStore = useLibraryStore();
const playerStore = usePlayerStore();

const tab = ref<'queue' | 'done' | 'errors' | 'all'>('queue');
const isSettingsOpen = ref(false);
const isSavingSettings = ref(false);
const isVerifyingAll = ref(false);

const quickSettings = ref({
  maxConcurrentDownloads: 3,
  globalSpeedLimitKb: 0,
});

// Drag & Drop state
const draggedTaskId = ref<string | number | null>(null);

// Individual Speed Limit Modal state
const speedModalTask = ref<DownloadTask | null>(null);
const taskSpeedLimitInput = ref<number>(0);

// Toast state
const toastMessage = ref<string | null>(null);
const toastType = ref<'success' | 'error' | 'info'>('info');
let toastTimer: any = null;

function showToast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
  toastMessage.value = msg;
  toastType.value = type;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastMessage.value = null;
  }, 4000);
}

onMounted(async () => {
  await downloadStore.fetchTasks();
  if (libraryStore.favorites.length === 0) {
    libraryStore.fetchFavorites().catch(() => {});
  }
  loadQuickSettings();
});

async function loadQuickSettings() {
  try {
    const s = await downloadStore.getQuickSettings();
    if (s) {
      quickSettings.value.maxConcurrentDownloads = s.maxConcurrentDownloads ?? 3;
      quickSettings.value.globalSpeedLimitKb = s.globalSpeedLimit > 0 ? Math.round(s.globalSpeedLimit / 1024) : 0;
    }
  } catch (e) {
    console.debug('[DownloadsView] Could not load quick settings:', e);
  }
}

async function saveSettings() {
  isSavingSettings.value = true;
  try {
    const payload = {
      maxConcurrentDownloads: quickSettings.value.maxConcurrentDownloads,
      globalSpeedLimit: (quickSettings.value.globalSpeedLimitKb || 0) * 1024,
    };
    await downloadStore.saveQuickSettings(payload);
    showToast('Paramètres de débit appliqués avec succès !', 'success');
    isSettingsOpen.value = false;
  } catch (e: any) {
    showToast(e.message || 'Erreur lors de la sauvegarde.', 'error');
  } finally {
    isSavingSettings.value = false;
  }
}

// Catégories de tâches
const activeAndQueuedCount = computed(() => {
  return downloadStore.tasks.filter((t) => {
    const s = (t.status || '').toLowerCase();
    return ['downloading', 'queued', 'paused', 'pending', 'scheduled', 'retrying', 'muxing'].includes(s);
  }).length;
});

const completedCount = computed(() => {
  return downloadStore.tasks.filter((t) => (t.status || '').toLowerCase() === 'completed').length;
});

const errorTasksCount = computed(() => {
  return downloadStore.tasks.filter((t) => {
    const s = (t.status || '').toLowerCase();
    return ['error', 'failed', 'cancelled'].includes(s);
  }).length;
});

const queuedTasks = computed(() => {
  return downloadStore.tasks.filter((t) => (t.status || '').toLowerCase() === 'queued');
});

const filteredTasks = computed<DownloadTask[]>(() => {
  const list = downloadStore.tasks;
  if (tab.value === 'queue') {
    return list.filter((t) => {
      const s = (t.status || '').toLowerCase();
      return ['downloading', 'queued', 'paused', 'pending', 'scheduled', 'retrying', 'muxing'].includes(s);
    });
  }
  if (tab.value === 'done') {
    return list.filter((t) => (t.status || '').toLowerCase() === 'completed');
  }
  if (tab.value === 'errors') {
    return list.filter((t) => {
      const s = (t.status || '').toLowerCase();
      return ['error', 'failed', 'cancelled'].includes(s);
    });
  }
  return list;
});

const emptyStateTitle = computed(() => {
  if (tab.value === 'queue') return 'Aucun téléchargement en cours ou en attente';
  if (tab.value === 'done') return 'Aucun téléchargement terminé';
  if (tab.value === 'errors') return 'Aucun téléchargement en erreur';
  return 'Gestionnaire de téléchargements vide';
});

const emptyStateDescription = computed(() => {
  if (tab.value === 'queue') return 'Lancez des épisodes depuis une fiche animé pour démarrer des téléchargements.';
  if (tab.value === 'done') return 'Les épisodes terminés et vérifiés apparaîtront ici pour la lecture locale.';
  if (tab.value === 'errors') return 'Parfait ! Tous vos téléchargements se sont déroulés sans accroc.';
  return 'Vos téléchargements actifs et passés seront centralisés ici.';
});

function getAnimePoster(animeName?: string): string | null {
  if (!animeName) return null;
  const match = libraryStore.favorites.find(
    (f) => f.title.toLowerCase().trim() === animeName.toLowerCase().trim()
  );
  return match?.imageUrl || null;
}

function getInitials(name?: string): string {
  if (!name) return 'AN';
  const words = name.trim().split(/\s+/);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function getQueueIndex(taskId: string | number): number {
  const idx = queuedTasks.value.findIndex((t) => String(t.id) === String(taskId));
  return idx !== -1 ? idx + 1 : 1;
}

function getVisualProgress(task: DownloadTask): number {
  const s = (task.status || '').toLowerCase();
  if (s === 'completed') return 100;
  if (s === 'error' || s === 'failed') return Math.min(100, Math.max(10, task.progress || 0));
  return task.progress || 0;
}

function getStatusBadgeClass(task: DownloadTask): string {
  const s = (task.status || '').toLowerCase();
  if (s === 'completed') return 'badge-success';
  if (s === 'downloading' || s === 'muxing') return 'badge-source';
  if (s === 'paused') return 'badge-warning';
  if (s === 'error' || s === 'failed') return 'badge-danger';
  if (s === 'cancelled') return 'badge-neutral';
  return 'badge-blue';
}

function getStatusLabel(task: DownloadTask): string {
  const s = (task.status || '').toLowerCase();
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
    case 'muxing': return 'Muxing';
    default: return task.status;
  }
}

function getVerifBadgeClass(status?: string): string {
  if (status === 'VALID') return 'verif-valid';
  if (status === 'MISSING' || status === 'CORRUPTED' || status === 'EMPTY') return 'verif-err';
  return 'verif-warn';
}

function formatVerifLabel(task: DownloadTask): string {
  if (task.verificationStatus === 'VALID') {
    return task.formattedDuration ? `Vérifié • ${task.formattedDuration}` : 'Vérifié (Flux valide)';
  }
  if (task.verificationStatus === 'CORRUPTED') return 'Flux endommagé';
  if (task.verificationStatus === 'MISSING') return 'Fichier manquant';
  if (task.verificationStatus === 'EMPTY') return 'Fichier vide';
  return 'Non vérifié';
}

function formatSpeed(bytesPerSec?: number | null): string {
  if (!bytesPerSec || bytesPerSec <= 0) return '0 Ko/s';
  const mb = bytesPerSec / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(2)} Mo/s`;
  const kb = bytesPerSec / 1024;
  return `${kb.toFixed(1)} Ko/s`;
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '0 Mo';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} Go`;
  return `${mb.toFixed(1)} Mo`;
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

function formatDateTime(isoStr?: string | null): string {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return isoStr;
  }
}

// Drag & Drop Logic
function onDragStart(task: DownloadTask, event: DragEvent) {
  draggedTaskId.value = task.id;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', String(task.id));
  }
}

function onDragOver(_targetTask: DownloadTask, event: DragEvent) {
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move';
  }
}

async function onDrop(targetTask: DownloadTask, event: DragEvent) {
  event.preventDefault();
  const sourceId = draggedTaskId.value;
  if (!sourceId || String(sourceId) === String(targetTask.id)) return;

  const currentQueued = [...queuedTasks.value];
  const srcIdx = currentQueued.findIndex((t) => String(t.id) === String(sourceId));
  const tgtIdx = currentQueued.findIndex((t) => String(t.id) === String(targetTask.id));

  if (srcIdx !== -1 && tgtIdx !== -1) {
    const [moved] = currentQueued.splice(srcIdx, 1);
    currentQueued.splice(tgtIdx, 0, moved);
    const orderedIds = currentQueued.map((t) => t.id);

    try {
      await downloadStore.reorderTasks(orderedIds);
      showToast('Ordre de la file d\'attente mis à jour.', 'success');
    } catch {
      showToast('Erreur lors du réordonnancement.', 'error');
    }
  }
  draggedTaskId.value = null;
}

function onDragEnd() {
  draggedTaskId.value = null;
}

// Quick Actions
async function moveTaskToTop(task: DownloadTask) {
  try {
    await downloadStore.moveTaskToTop(task.id);
    showToast(`"${task.animeName}" placé en tête de file d'attente.`, 'success');
  } catch {
    showToast('Erreur lors du déplacement.', 'error');
  }
}

async function moveSeriesToTop(task: DownloadTask) {
  try {
    await downloadStore.moveSeriesToTop(task.animeName);
    showToast(`Tous les épisodes de "${task.animeName}" placés en priorité.`, 'success');
  } catch {
    showToast('Erreur lors de la priorisation de la série.', 'error');
  }
}

async function removeTask(task: DownloadTask) {
  try {
    await downloadStore.removeTask(task.id);
    showToast('Tâche retirée avec succès.', 'info');
  } catch {
    showToast('Erreur lors de la suppression.', 'error');
  }
}

async function redownloadTask(task: DownloadTask) {
  try {
    await downloadStore.redownloadTask(task.id);
    showToast(`Re-téléchargement relancé pour "${task.fileName}" !`, 'success');
    tab.value = 'queue';
  } catch {
    showToast('Erreur lors de la relance.', 'error');
  }
}

async function retryAllErrors() {
  const errTasks = downloadStore.tasks.filter((t) => {
    const s = (t.status || '').toLowerCase();
    return ['error', 'failed'].includes(s);
  });
  if (errTasks.length === 0) return;

  for (const t of errTasks) {
    try {
      await downloadStore.redownloadTask(t.id);
    } catch {}
  }
  showToast(`${errTasks.length} téléchargement(s) relancé(s) !`, 'success');
  tab.value = 'queue';
}

function confirmCancelAll() {
  if (window.confirm('Êtes-vous sûr de vouloir annuler tous les téléchargements actifs et en attente ?')) {
    downloadStore.cancelAll();
    showToast('Tous les téléchargements ont été annulés.', 'info');
  }
}

// Media Playback (Mode Cinéma local)
function playTask(task: DownloadTask) {
  playerStore.playLocalFile(task.id, task.animeName, task.episodeNumber, task.fileName);
}

// Verification Handlers
async function verifySingleTask(task: DownloadTask) {
  showToast(`Vérification d'intégrité de "${task.fileName}"...`, 'info');
  try {
    const res = await downloadStore.verifyTask(task.id);
    if (res?.valid) {
      showToast(`Fichier valide ! Durée : ${res.formattedDuration || 'OK'} (${res.formattedSize || ''})`, 'success');
    } else {
      showToast(`Alerte intégrité : ${res?.error || 'Flux vidéo non conforme.'}`, 'error');
    }
  } catch {
    showToast('Erreur lors de la vérification.', 'error');
  }
}

async function verifyAll() {
  isVerifyingAll.value = true;
  showToast('Vérification globale en cours...', 'info');
  try {
    const res = await downloadStore.verifyAllTasks();
    showToast(`Vérification terminée : ${res?.valid ?? 0} valide(s), ${res?.invalid ?? 0} corrompu(s).`, 'success');
  } catch {
    showToast('Erreur lors de la vérification globale.', 'error');
  } finally {
    isVerifyingAll.value = false;
  }
}

// Speed limit modal
function openSpeedLimitModal(task: DownloadTask) {
  speedModalTask.value = task;
  taskSpeedLimitInput.value = task.maxSpeedLimit && task.maxSpeedLimit > 0 ? Math.round(task.maxSpeedLimit / 1024) : 0;
}

async function applyTaskSpeedLimit() {
  if (!speedModalTask.value) return;
  try {
    const limitBytes = (taskSpeedLimitInput.value || 0) * 1024;
    await downloadStore.setTaskSpeedLimit(speedModalTask.value.id, limitBytes);
    showToast(
      taskSpeedLimitInput.value > 0
        ? `Plafond de vitesse fixé à ${taskSpeedLimitInput.value} Ko/s.`
        : 'Plafond de vitesse retiré (Illimité).',
      'success'
    );
    speedModalTask.value = null;
  } catch {
    showToast('Erreur lors de l\'application du plafond.', 'error');
  }
}
</script>

<style scoped>
.downloads-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Toolbar & Tabs */
.download-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  padding: 12px 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.download-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tab-badge {
  font-size: 11px;
  background: var(--line-strong);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  margin-left: 6px;
  font-weight: 600;
}

.tab-badge.badge-queue {
  background: rgba(56, 189, 248, 0.2);
  color: var(--blue);
}

.tab-badge.badge-done {
  background: rgba(52, 211, 153, 0.2);
  color: var(--green);
}

.tab-badge.badge-error {
  background: rgba(248, 113, 113, 0.2);
  color: var(--red);
}

.download-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.btn-icon-round {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-pill);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--input-bg);
  border: 1px solid var(--line);
  color: var(--text);
  cursor: pointer;
  transition: all var(--transition);
}

.btn-icon-round:hover,
.btn-icon-round.active {
  background: var(--accent-container);
  color: var(--accent);
  border-color: var(--accent);
}

/* Quick Settings Accordion */
.quick-settings-panel {
  background: var(--panel-strong);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: var(--card-shadow);
}

.quick-settings-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.quick-settings-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 15px;
  color: var(--text);
}

.quick-settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.qs-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.qs-item-wide {
  grid-column: 1 / -1;
}

.qs-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.qs-control {
  display: flex;
  align-items: center;
  gap: 10px;
}

.qs-control-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qs-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.qs-number-input {
  width: 140px;
  padding: 6px 12px;
}

.qs-hint,
.qs-unit {
  font-size: 12px;
  color: var(--muted);
}

.speed-presets {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.preset-chip {
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  background: var(--input-bg);
  border: 1px solid var(--line);
  color: var(--muted);
  cursor: pointer;
  transition: all var(--transition);
}

.preset-chip:hover {
  border-color: var(--accent);
  color: var(--text);
}

.preset-chip.active {
  background: var(--accent-container);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

/* Queue hint */
.queue-reorder-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px dashed rgba(56, 189, 248, 0.3);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--blue);
}

/* Task Row Cards */
.tasks-table {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-row-card {
  display: flex;
  align-items: center;
  padding: 14px 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  gap: 16px;
  transition: all var(--transition);
}

.task-row-card:hover {
  border-color: var(--line-strong);
  background: var(--panel-strong);
}

.task-row-card.is-dragging {
  opacity: 0.4;
  border-style: dashed;
  border-color: var(--accent);
}

/* Drag Handle */
.task-drag-handle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: grab;
  color: var(--faint);
  user-select: none;
}

.task-drag-handle:active {
  cursor: grabbing;
}

.queue-order-badge {
  font-size: 11px;
  font-weight: 700;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
}

.drag-dots {
  font-size: 16px;
  letter-spacing: -2px;
}

/* Cover Avatar */
.task-cover {
  width: 48px;
  height: 64px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--input-bg);
  border: 1px solid var(--line);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.task-cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.task-cover-fallback {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 14px;
  color: var(--accent);
  background: var(--accent-container);
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Main Column */
.task-col-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.task-anime-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 420px;
}

.quality-tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(157, 111, 255, 0.15);
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 0.5px;
}

.source-tag {
  font-size: 11px;
  color: var(--faint);
}

.task-meta-line {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
  align-items: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-ep-number {
  font-weight: 500;
  color: var(--text);
}

.task-filename {
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-scheduled-time {
  color: #ff9f43;
  font-weight: 500;
}

/* Progress bar */
.progress-bar-container {
  width: 100%;
  height: 6px;
  background: var(--input-bg);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  transition: width 0.3s ease;
}

.progress-bar-fill.active {
  box-shadow: 0 0 10px rgba(var(--accent-rgb), 0.8);
}

.progress-bar-fill.paused {
  background: var(--yellow);
}

.progress-bar-fill.error {
  background: var(--red);
}

.progress-bar-fill.completed {
  background: var(--green);
}

/* Stats line */
.task-stats-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
  flex-wrap: wrap;
  gap: 6px;
}

.task-stats-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-stats-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.live-speed {
  color: var(--text);
  font-weight: 600;
}

.live-eta {
  color: var(--muted);
  font-weight: 400;
}

/* Verif & Limit Badges */
.verif-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  font-weight: 600;
}

.verif-valid {
  background: rgba(52, 211, 153, 0.15);
  color: var(--green);
  border: 1px solid rgba(52, 211, 153, 0.3);
}

.verif-err {
  background: rgba(248, 113, 113, 0.15);
  color: var(--red);
  border: 1px solid rgba(248, 113, 113, 0.3);
}

.verif-warn {
  background: rgba(251, 191, 36, 0.15);
  color: var(--yellow);
  border: 1px solid rgba(251, 191, 36, 0.3);
}

.speed-limit-chip {
  border: none;
  background: var(--line);
  color: var(--muted);
  font-size: 11px;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: all var(--transition);
}

.speed-limit-chip:hover {
  background: var(--line-strong);
  color: var(--text);
}

/* Error box */
.task-error-box {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.25);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: 12px;
  color: var(--red);
  line-height: 1.4;
}

/* Action buttons */
.task-col-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.btn-icon {
  width: 32px;
  height: 32px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
}

/* Modal Styling */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  width: 90%;
  max-width: 480px;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  font-size: 16px;
  margin: 0;
  color: var(--text);
}

.modal-sub {
  font-size: 13px;
  color: var(--muted);
  margin: 0 0 14px;
}

.modal-input-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.modal-unit {
  font-size: 13px;
  color: var(--muted);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.stat-red strong {
  color: var(--red);
}

.clickable {
  cursor: pointer;
  transition: transform var(--transition);
}

.clickable:hover {
  transform: translateY(-2px);
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
