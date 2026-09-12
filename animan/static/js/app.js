'use strict';

const THEME_KEY = 'animan-theme';
let sseSource = null;
let plyrInstance = null;
let cinemaPlyrInstance = null;
let cinemaHlsInstance = null;
let currentPlayingEpNum = null;
let currentRange = 'all';

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  highlightActiveNav();
  bindGlobalSettingsToggle();
  loadEpisodeSizes();
  buildVersionFilters();
  checkFavoriteStatus();
  refreshDownloadBadge();
  bindPlayActionButtons();
  initShortcuts();
  initSearchAutocomplete();
  initEpisodeRangePagination();

  if (document.getElementById('download-list')) {
    initSSE();
    refreshDownloadStats();
    initDragAndDrop();
    initScheduledTicker();
  }

  if (window.location.pathname === '/settings' || document.getElementById('save-settings-btn')) {
    initDownloadSettingsPanel();
  }
});


function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || 'dark';
  applyTheme(saved);
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.querySelectorAll('.icon-moon').forEach(el => { el.style.display = theme === 'dark' ? '' : 'none'; });
  document.querySelectorAll('.icon-sun').forEach(el => { el.style.display = theme === 'light' ? '' : 'none'; });
  localStorage.setItem(THEME_KEY, theme);
}

function highlightActiveNav() {
  const path = window.location.pathname;
  const entries = [
    ['/downloads', 'nav-downloads', 'mob-nav-downloads'],
    ['/library', 'nav-library', 'mob-nav-library'],
    ['/history', 'nav-history', ''],
    ['/settings', 'nav-settings', 'mob-nav-settings'],
    ['/', 'nav-home', 'mob-nav-home']
  ];
  const match = entries.find(([prefix]) => prefix === '/' ? path === '/' : path.startsWith(prefix));
  if (match) {
    if (match[1]) document.getElementById(match[1])?.classList.add('active');
    if (match[2]) document.getElementById(match[2])?.classList.add('active');
  }
}

function bindGlobalSettingsToggle() {
  document.querySelectorAll('[data-toggle-download-settings], #settings-shortcut').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const panel = document.getElementById('settings-panel');
      if (panel) {
        e.preventDefault();
        panel.classList.toggle('open');
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        window.location.href = '/settings';
      }
    });
  });
}

function initDownloadSettingsPanel() {
  const panel = document.getElementById('settings-panel');
  const toggle = document.getElementById('toggle-settings-btn');
  const save = document.getElementById('save-settings-btn');
  const uaSelect = document.getElementById('user-agent-select');
  const customUaGroup = document.getElementById('custom-ua-group');
  const customUaInput = document.getElementById('custom-ua-input');

  if (window.location.hash === '#settings-panel' || new URLSearchParams(window.location.search).has('settings')) {
    panel?.classList.add('open');
    setTimeout(() => {
      panel?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
  }

  toggle?.addEventListener('click', () => panel?.classList.toggle('open'));
  uaSelect?.addEventListener('change', () => {
    if (customUaGroup) customUaGroup.style.display = uaSelect.value === 'Custom' ? 'grid' : 'none';
  });

  fetch('/api/download/settings')
    .then(r => r.json())
    .then(settings => {
      const maxInput = document.getElementById('max-concurrent-input');
      const speedInput = document.getElementById('global-speed-input-settings');
      const plexInput = document.getElementById('plex-org-cb');
      const serverSelect = document.getElementById('voiranime-server-select');
      if (maxInput) maxInput.value = settings.maxConcurrentDownloads ?? 3;
      if (speedInput) speedInput.value = settings.globalSpeedLimit > 0 ? Math.round(settings.globalSpeedLimit / 1024) : '';
      if (plexInput) plexInput.checked = !!settings.plexOrganization;
      if (serverSelect && settings.voiranimeDefaultServer) {
        serverSelect.value = settings.voiranimeDefaultServer;
      }
      if (settings.selectedUserAgent && uaSelect) {
        const standard = ['Random (Rotator)', 'Chrome', 'Firefox', 'Safari', 'Edge'];
        uaSelect.value = standard.includes(settings.selectedUserAgent) ? settings.selectedUserAgent : 'Custom';
        if (customUaInput && uaSelect.value === 'Custom') customUaInput.value = settings.selectedUserAgent;
        if (customUaGroup) customUaGroup.style.display = uaSelect.value === 'Custom' ? 'grid' : 'none';
      }
      
      const ffmpegBadge = document.getElementById('ffmpeg-status-badge');
      if (ffmpegBadge) {
        if (settings.ffmpegAvailable) {
          ffmpegBadge.textContent = 'Opérationnel';
          ffmpegBadge.className = 'status-badge badge-ok';
        } else {
          ffmpegBadge.textContent = 'Non trouvé (Muxing désactivé)';
          ffmpegBadge.className = 'status-badge badge-err';
        }
      }
    })
    .catch(() => {});

  save?.addEventListener('click', async () => {
    const maxConcurrent = parseInt(document.getElementById('max-concurrent-input')?.value || '3', 10);
    const speedKb = parseInt(document.getElementById('global-speed-input-settings')?.value || '0', 10);
    const plexOrganization = !!document.getElementById('plex-org-cb')?.checked;
    const voiranimeDefaultServer = document.getElementById('voiranime-server-select')?.value || 'auto';
    let selectedUserAgent = uaSelect?.value || 'Random (Rotator)';

    if (selectedUserAgent === 'Custom') {
      selectedUserAgent = customUaInput?.value.trim() || '';
      if (!selectedUserAgent) {
        showToast('Veuillez saisir un User-Agent personnalise', 'error');
        return;
      }
    }

    const body = {
      maxConcurrentDownloads: maxConcurrent,
      globalSpeedLimit: speedKb * 1024,
      plexOrganization,
      selectedUserAgent,
      voiranimeDefaultServer,
    };

    try {
      const resp = await fetch('/api/download/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await resp.json();
      if (data.success) {
        showToast('Parametres mis a jour', 'success');
      } else {
        showToast(data.error || 'Erreur lors de la mise a jour', 'error');
      }
    } catch (error) {
      showToast('Erreur de connexion', 'error');
    }
  });
}

function setSpeedLimitPreset(kb) {
  const input = document.getElementById('global-speed-input-settings');
  if (input) {
    input.value = kb > 0 ? kb : '';
    document.querySelectorAll('.speed-preset-chip').forEach(chip => {
      chip.classList.toggle('active', chip.getAttribute('data-kb') == String(kb));
    });
  }
}
window.setSpeedLimitPreset = setSpeedLimitPreset;

const episodeSizeCache = new Map();
let activeSizeFetches = 0;
const sizeFetchQueue = [];

function processSizeFetchQueue() {
  const MAX_CONCURRENT_SIZE_FETCHES = 4;
  while (activeSizeFetches < MAX_CONCURRENT_SIZE_FETCHES && sizeFetchQueue.length > 0) {
    const { span, url, server, quality } = sizeFetchQueue.shift();
    const cacheKey = `${url}::${server || ''}::${quality || ''}`;
    if (episodeSizeCache.has(cacheKey)) {
      applySizeData(span, episodeSizeCache.get(cacheKey));
      continue;
    }

    activeSizeFetches++;
    let fetchUrl = '/api/episode/size?url=' + encodeURIComponent(url);
    if (server && server !== 'auto') fetchUrl += '&server=' + encodeURIComponent(server);
    if (quality && quality !== 'auto') fetchUrl += '&quality=' + encodeURIComponent(quality);

    fetch(fetchUrl)
      .then(r => r.json())
      .then(data => {
        episodeSizeCache.set(cacheKey, data);
        applySizeData(span, data);
      })
      .catch(() => {
        span.textContent = '-';
      })
      .finally(() => {
        activeSizeFetches--;
        processSizeFetchQueue();
      });
  }
}

function applySizeData(span, data) {
  if (!span) return;
  span.textContent = data && data.success ? data.formattedSize : '-';
  const row = span.closest('.episode-item');
  if (data && data.success && data.subtitleUrl && row) {
    const sub = row.querySelector('.subtitle-cb-label');
    if (sub) sub.classList.add('is-available');
  }
  if (row && data && data.success) {
    if (data.currentServer) row.dataset.server = data.currentServer;
    if (data.currentQuality) row.dataset.quality = data.currentQuality;
    if (data.qualitiesSizes) {
      row.dataset.qualitiesSizes = JSON.stringify(data.qualitiesSizes);
    }

    const qSelect = row.querySelector('.episode-quality-select');
    if (qSelect && data.qualities && data.qualities.length > 0) {
      qSelect.innerHTML = '';
      data.qualities.forEach(q => {
        const opt = document.createElement('option');
        opt.value = q;
        opt.textContent = q;
        if (data.currentQuality && q.toLowerCase().includes(data.currentQuality.toLowerCase())) {
          opt.selected = true;
        }
        qSelect.appendChild(opt);
      });
      qSelect.style.display = 'inline-block';
    }
  }
}

async function onEpisodeQualityChange(selectEl) {
  const row = selectEl.closest('.episode-item');
  if (!row) return;
  const url = row.dataset.url;
  const quality = selectEl.value;
  const server = row.dataset.server || document.getElementById('batch-server-select')?.value || '';
  row.dataset.quality = quality;
  const span = row.querySelector('.episode-size');

  // Vérifier si la taille est déjà connue localement dans qualitiesSizes
  if (row.dataset.qualitiesSizes) {
    try {
      const qSizes = JSON.parse(row.dataset.qualitiesSizes);
      if (qSizes[quality]) {
        if (span) span.textContent = qSizes[quality];
        return;
      }
      for (const [k, v] of Object.entries(qSizes)) {
        if (k.toLowerCase().includes(quality.toLowerCase()) || quality.toLowerCase().includes(k.toLowerCase())) {
          if (span) span.textContent = v;
          return;
        }
      }
    } catch (e) {}
  }

  if (span) span.textContent = '...';
  try {
    const qParam = encodeURIComponent(quality);
    const sParam = server && server !== 'auto' ? `&server=${encodeURIComponent(server)}` : '';
    const resp = await fetch(`/api/episode/size?url=${encodeURIComponent(url)}&quality=${qParam}${sParam}`);
    const data = await resp.json();
    if (data.success && span) {
      span.textContent = data.formattedSize;
      if (data.qualitiesSizes) {
        row.dataset.qualitiesSizes = JSON.stringify(data.qualitiesSizes);
      }
    }
  } catch (e) {
    if (span) span.textContent = '-';
  }
}

function onBatchServerChange(server) {
  // Réinitialiser la file d'attente pour éviter les requêtes obsolètes
  sizeFetchQueue.length = 0;
  document.querySelectorAll('.episode-item').forEach(row => {
    row.dataset.server = server;
    delete row.dataset.qualitiesSizes;
    const span = row.querySelector('.episode-size');
    const url = row.dataset.url;
    if (span && url) {
      span.textContent = '...';
      sizeFetchQueue.push({
        span,
        url,
        server: server && server !== 'auto' ? server : '',
        quality: row.dataset.quality || ''
      });
    }
  });
  processSizeFetchQueue();
}

function onBatchQualityChange(quality) {
  document.querySelectorAll('.episode-item').forEach(row => {
    row.dataset.quality = quality;
    const qSelect = row.querySelector('.episode-quality-select');
    if (qSelect && quality !== 'auto') {
      for (let i = 0; i < qSelect.options.length; i++) {
        if (qSelect.options[i].value.toLowerCase().includes(quality.toLowerCase())) {
          qSelect.selectedIndex = i;
          break;
        }
      }
    }
    const span = row.querySelector('.episode-size');
    const url = row.dataset.url;
    if (span && url && quality !== 'auto') {
      // Vérifier si la taille est déjà connue localement
      if (row.dataset.qualitiesSizes) {
        try {
          const qSizes = JSON.parse(row.dataset.qualitiesSizes);
          let found = false;
          for (const [k, v] of Object.entries(qSizes)) {
            if (k.toLowerCase().includes(quality.toLowerCase()) || quality.toLowerCase().includes(k.toLowerCase())) {
              span.textContent = v;
              found = true;
              break;
            }
          }
          if (found) return;
        } catch (e) {}
      }

      span.textContent = '...';
      const server = row.dataset.server || document.getElementById('batch-server-select')?.value || '';
      sizeFetchQueue.push({
        span,
        url,
        server: server && server !== 'auto' ? server : '',
        quality
      });
    }
  });
  processSizeFetchQueue();
}

function loadEpisodeSizes() {
  const nodes = document.querySelectorAll('.episode-size[data-url]');
  if (!nodes.length) return;

  const batchServerSel = document.getElementById('batch-server-select');
  if (batchServerSel) {
    fetch('/api/download/settings')
      .then(r => r.json())
      .then(s => {
        if (s.voiranimeDefaultServer && s.voiranimeDefaultServer !== 'auto') {
          batchServerSel.value = s.voiranimeDefaultServer;
        }
      })
      .catch(() => {});
  }

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const span = entry.target;
      observer.unobserve(span);
      const url = span.dataset.url;
      if (!url) return;

      const server = batchServerSel?.value || '';
      const quality = document.getElementById('batch-quality-select')?.value || '';
      const cacheKey = `${url}::${server || ''}::${quality || ''}`;
      if (episodeSizeCache.has(cacheKey)) {
        applySizeData(span, episodeSizeCache.get(cacheKey));
        return;
      }

      sizeFetchQueue.push({ span, url, server, quality });
      processSizeFetchQueue();
    });
  }, { rootMargin: '40px' });

  nodes.forEach(node => observer.observe(node));
}

function buildVersionFilters() {
  const filterContainer = document.getElementById('version-filter');
  if (!filterContainer) return;

  const items = [...document.querySelectorAll('.episode-item')];
  const versions = [...new Set(items.map(item => item.dataset.version).filter(Boolean))];
  if (versions.length <= 1) return;

  filterContainer.appendChild(createFilterBtn('Tous', true, () => filterEpisodes('ALL')));
  versions.forEach(version => {
    filterContainer.appendChild(createFilterBtn(version, false, () => filterEpisodes(version)));
  });
}

function createFilterBtn(label, active, onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ver-filter-btn' + (active ? ' active' : '');
  btn.textContent = label;
  btn.addEventListener('click', () => {
    document.querySelectorAll('.ver-filter-btn').forEach(item => item.classList.remove('active'));
    btn.classList.add('active');
    onClick();
  });
  return btn;
}

function filterEpisodes(version) {
  document.querySelectorAll('.episode-item').forEach(item => {
    item.style.display = version === 'ALL' || item.dataset.version === version ? '' : 'none';
  });
}

function onEpisodeCheckChange() {
  const checked = document.querySelectorAll('.episode-check:checked');
  const btn = document.getElementById('dl-selected-btn');
  const info = document.getElementById('selected-count-text');
  if (btn && !btn.classList.contains('is-loading')) btn.disabled = checked.length === 0;
  if (info) info.textContent = checked.length + ' sélectionné(s)';
}

function toggleSelectAll(checkbox) {
  document.querySelectorAll('.episode-check').forEach(cb => {
    const row = cb.closest('.episode-item');
    if (!row || row.style.display === 'none') return;
    cb.checked = checkbox.checked;
  });
  onEpisodeCheckChange();
}

async function downloadEpisode(btn) {
  const url = btn.dataset.url;
  const epNum = parseInt(btn.dataset.num, 10);
  const subtitleUrl = btn.dataset.subtitle || '';
  const row = btn.closest('.episode-item');
  const downloadSubtitles = row?.querySelector('.subtitle-check')?.checked || false;
  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : 'Anime';
  const source = typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga';
  const fileName = sanitizeFilename(animeName + ' - Episode ' + epNum + '.mp4');

  const selectedServer = row?.dataset.server || document.getElementById('batch-server-select')?.value || null;
  const selectedQuality = row?.querySelector('.episode-quality-select')?.value || row?.dataset.quality || document.getElementById('batch-quality-select')?.value || null;

  if (source === 'voir-anime' && !selectedQuality && (!row?.querySelector('.episode-quality-select') || row?.querySelector('.episode-quality-select').style.display === 'none')) {
    await handleVoirAnimeDownload(url, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, null, selectedServer);
    return;
  }

  btn.disabled = true;
  const origContent = btn.innerHTML;
  btn.innerHTML = '<span class="spinner-sm"></span>';
  try {
    await startDownloadRequest(animeName, epNum, url, fileName, subtitleUrl, null, 0, downloadSubtitles, selectedServer, selectedQuality);
  } finally {
    setTimeout(() => {
      btn.disabled = false;
      btn.innerHTML = origContent;
    }, 1200);
  }
}

async function handleVoirAnimeDownload(episodeUrl, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, scheduledTime, preferredServer) {
  showToast('Résolution des qualités disponibles...', 'info');
  try {
    let qUrl = '/api/voiranime/download-info?episodeUrl=' + encodeURIComponent(episodeUrl);
    if (preferredServer && preferredServer !== 'auto') {
      qUrl += '&server=' + encodeURIComponent(preferredServer);
    }
    const resp = await fetch(qUrl);
    const info = await resp.json();
    let qualities = {};
    try { qualities = JSON.parse(info.videoQualities || '{}'); } catch (error) {}

    if (Object.keys(qualities).length > 1) {
      showQualityModal(qualities, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, scheduledTime, info.videoChunks, info.serverType);
    } else {
      await startDownloadRequest(animeName, epNum, info.videoUrl || episodeUrl, fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, info.serverType, info.selectedQuality);
    }
  } catch (error) {
    showToast('Erreur de résolution: ' + error.message, 'error');
  }
}

function showQualityModal(qualities, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, scheduledTime, chunksJson, serverType) {
  const modal = document.getElementById('quality-modal');
  const list = document.getElementById('quality-list');
  if (!modal || !list) return;

  list.innerHTML = '';
  Object.entries(qualities).forEach(([label, url]) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'quality-item';
    item.innerHTML = `<span class="quality-label">${escapeHtml(label)}</span><span class="quality-download">Télécharger</span>`;
    item.addEventListener('click', async () => {
      modal.style.display = 'none';
      await startDownloadRequest(animeName, epNum, url, label + ' - ' + fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, serverType, label);
    });
    list.appendChild(item);
  });

  if (chunksJson && chunksJson !== '[]') {
    try {
      const chunks = JSON.parse(chunksJson);
      if (chunks.length > 1) {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'quality-item';
        item.innerHTML = `<span class="quality-label">Tous les morceaux (${chunks.length})</span><span class="quality-download">Concaténer</span>`;
        item.addEventListener('click', async () => {
          modal.style.display = 'none';
          await startDownloadRequest(animeName, epNum, chunks[0], fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, serverType, 'Chunks');
        });
        list.appendChild(item);
      }
    } catch (error) {}
  }

  modal.style.display = 'flex';
}

async function startDownloadRequest(animeName, episodeNumber, url, fileName, subtitleUrl, scheduledTime, speedLimit, downloadSubtitles, selectedServer, selectedQuality) {
  const body = { animeName, episodeNumber, url, fileName, downloadSubtitles };
  if (subtitleUrl) body.subtitleUrl = subtitleUrl;
  if (scheduledTime) body.scheduledTime = scheduledTime;
  if (speedLimit) body.speedLimit = String(speedLimit);
  if (selectedServer && selectedServer !== 'auto') body.selectedServer = selectedServer;
  if (selectedQuality && selectedQuality !== 'auto') body.selectedQuality = selectedQuality;

  try {
    const resp = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    if (data.success) {
      showToast((data.message || 'Téléchargement lancé !') + ' <a href="/downloads" class="toast-link">Voir la file</a>', 'success');
      refreshDownloadBadge();

      // Update episode row badge if on anime-detail page
      const row = document.querySelector(`.episode-item[data-num="${episodeNumber}"]`);
      if (row && !row.querySelector('.ep-queued-badge') && !row.querySelector('.ep-done-badge')) {
        const badge = document.createElement('span');
        badge.className = 'ep-queued-badge';
        badge.textContent = 'En file d\'attente';
        const titleEl = row.querySelector('.episode-title');
        if (titleEl) {
          titleEl.after(badge);
        } else {
          row.appendChild(badge);
        }
      }
    } else {
      showToast(data.error || 'Erreur de téléchargement', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion au serveur : ' + (err.message || err), 'error');
  }
}

async function downloadSelected() {
  const checked = [...document.querySelectorAll('.episode-check:checked')];
  if (!checked.length) return;

  const btn = document.getElementById('dl-selected-btn');
  const origBtnContent = btn ? btn.innerHTML : null;
  if (btn) {
    btn.classList.add('is-loading');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm"></span> <span>Lancement en cours...</span>';
  }

  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : 'Anime';
  const source = typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga';
  const scheduledTime = document.getElementById('schedule-input')?.value || '';
  const batchServer = document.getElementById('batch-server-select')?.value || null;
  const batchQuality = document.getElementById('batch-quality-select')?.value || null;

  const episodes = checked.map(cb => {
    const row = cb.closest('.episode-item');
    const num = parseInt(row.dataset.num, 10);
    const epServer = row.dataset.server || batchServer;
    const epQuality = row.querySelector('.episode-quality-select')?.value || row.dataset.quality || batchQuality;
    return {
      number: String(num),
      url: row.dataset.url,
      fileName: sanitizeFilename(animeName + ' - Episode ' + num + '.mp4'),
      subtitleUrl: row.dataset.subtitle || '',
      downloadSubtitles: String(row.querySelector('.subtitle-check')?.checked || false),
      scheduledTime,
      selectedServer: epServer && epServer !== 'auto' ? epServer : null,
      selectedQuality: epQuality && epQuality !== 'auto' ? epQuality : null
    };
  });

  try {
    if (source === 'voir-anime' && episodes.length === 1) {
      await handleVoirAnimeDownload(episodes[0].url, animeName, parseInt(episodes[0].number, 10), episodes[0].fileName, episodes[0].subtitleUrl, episodes[0].downloadSubtitles === 'true', scheduledTime || null);
      refreshDownloadBadge();
      return;
    }

    const resp = await fetch('/api/download/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animeName, episodes })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(`${episodes.length} épisode(s) ajouté(s) aux téléchargements ! <a href="/downloads" class="toast-link">Voir la file</a>`, 'success');

      // Mark rows with queued badge
      checked.forEach(cb => {
        const row = cb.closest('.episode-item');
        if (row && !row.querySelector('.ep-queued-badge') && !row.querySelector('.ep-done-badge')) {
          const badge = document.createElement('span');
          badge.className = 'ep-queued-badge';
          badge.textContent = 'En file d\'attente';
          const titleEl = row.querySelector('.episode-title');
          if (titleEl) {
            titleEl.after(badge);
          } else {
            row.appendChild(badge);
          }
        }
        cb.checked = false;
      });

      const selectAll = document.getElementById('select-all-cb');
      if (selectAll) selectAll.checked = false;
      refreshDownloadBadge();
    } else {
      showToast(data.error || 'Erreur lors du téléchargement par lot', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion au serveur : ' + (err.message || err), 'error');
  } finally {
    if (btn) {
      btn.classList.remove('is-loading');
      if (origBtnContent) btn.innerHTML = origBtnContent;
      btn.disabled = false;
    }
    onEpisodeCheckChange();
  }
}

async function playEpisode(btn) {
  const url = btn.dataset.url;
  const epNum = btn.dataset.num;
  const source = typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga';
  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : '';
  const animeUrl = typeof ANIME_URL !== 'undefined' ? ANIME_URL : '';
  const row = btn.closest('.episode-item');
  const version = row?.dataset.version || '';
  const server = row?.dataset.server || document.getElementById('batch-server-select')?.value || '';
  const quality = row?.dataset.quality || document.getElementById('batch-quality-select')?.value || '';

  showToast('Résolution du flux vidéo...', 'info');
  try {
    const params = new URLSearchParams({
      animeName,
      animeUrl,
      episodeUrl: url,
      episodeNumber: epNum,
      version,
      source
    });
    if (server && server !== 'auto') params.set('server', server);
    if (quality && quality !== 'auto') params.set('quality', quality);

    const resp = await fetch(`/api/media/stream/resolve?${params.toString()}`);
    const data = await resp.json();

    if (!resp.ok || !data.success) {
      showToast(data.error || 'Flux vidéo introuvable', 'error');
      return;
    }

    const videoUrl = data.streamUrl;
    const tracks = data.subtitles || [];
    const isDownloaded = Boolean(data.isDownloaded);

    // Mettre à jour visuellement la ligne et le bouton
    if (row && isDownloaded) {
      row.classList.add('ep-downloaded');
      row.dataset.downloaded = 'true';
      btn.classList.add('btn-play-local');
      btn.classList.remove('btn-play-stream');
      btn.title = 'Lecture locale (Disque dur)';
    }

    if (isDownloaded) {
      showToast('Lecture locale depuis le disque dur', 'success');
    } else {
      const srvLabel = data.serverType && data.serverType !== 'unknown' ? data.serverType : 'En ligne';
      showToast(`Streaming direct depuis ${srvLabel}...`, 'info');
    }

    const sourceMeta = {
      isDownloaded,
      sourceType: data.sourceType,
      serverType: data.serverType,
      selectedQuality: data.selectedQuality,
      qualities: data.qualities,
      filePath: data.filePath
    };

    const cinemaModal = document.getElementById('cinema-modal');
    if (cinemaModal) {
      openCinemaModal(videoUrl, `${animeName} - Épisode ${epNum}`, tracks, epNum, sourceMeta);
    } else {
      const playerSection = document.getElementById('player-section');
      const video = document.getElementById('plyr-player');
      if (playerSection && video) {
        video.innerHTML = `<source src="${videoUrl}" type="video/mp4"/>`;
        tracks.forEach(track => {
          const trackEl = document.createElement('track');
          trackEl.kind = 'subtitles';
          trackEl.label = track.label;
          trackEl.srclang = track.srclang;
          trackEl.src = track.src;
          if (track.default) trackEl.setAttribute('default', '');
          video.appendChild(trackEl);
        });
        video.load();
        playerSection.style.display = 'block';
        playerSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        if (window.Plyr) {
          if (!plyrInstance) {
            plyrInstance = new Plyr('#plyr-player', {
              controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'fullscreen'],
              captions: { active: true, update: true, language: 'fr' }
            });
          } else {
            plyrInstance.source = { type: 'video', sources: [{ src: videoUrl, type: 'video/mp4' }], tracks };
          }
          plyrInstance.play().catch(() => {});
        } else {
          video.play().catch(() => {});
        }
      }
    }

    if (animeUrl) {
      await fetch('/api/progress/watched', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ animeUrl, animeName, episodeNumber: String(epNum), version })
      });
      row?.classList.add('ep-watched');
    }
  } catch (error) {
    showToast('Erreur lecteur: ' + error.message, 'error');
  }
}

function openCinemaModal(videoUrl, title, tracks = [], epNum = null, sourceMeta = null) {
  const modal = document.getElementById('cinema-modal');
  const video = document.getElementById('cinema-player');
  const titleEl = document.getElementById('cinema-title');
  const infoEl = document.getElementById('cinema-ep-info');
  const badgeEl = document.getElementById('cinema-source-badge');
  if (!modal || !video) return;

  if (titleEl && title) titleEl.textContent = title;
  if (infoEl && epNum) infoEl.textContent = `Épisode ${epNum}`;
  currentPlayingEpNum = epNum;

  // Mise à jour du badge de source
  if (badgeEl) {
    if (sourceMeta && sourceMeta.isDownloaded) {
      badgeEl.className = 'cinema-badge badge-local';
      badgeEl.innerHTML = '<svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> Disque dur (Local)';
      badgeEl.style.display = 'inline-flex';
    } else if (sourceMeta && !sourceMeta.isDownloaded) {
      badgeEl.className = 'cinema-badge badge-remote';
      const srv = (sourceMeta.serverType && sourceMeta.serverType !== 'unknown') ? sourceMeta.serverType : 'En ligne';
      const q = sourceMeta.selectedQuality && sourceMeta.selectedQuality !== 'auto' ? ` • ${sourceMeta.selectedQuality}` : '';
      badgeEl.innerHTML = `<svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M5 3l14 9-14 9V3z"/></svg> Streaming (${srv}${q})`;
      badgeEl.style.display = 'inline-flex';
    } else {
      badgeEl.style.display = 'none';
    }
  }

  modal.classList.add('open');

  if (cinemaHlsInstance) {
    cinemaHlsInstance.destroy();
    cinemaHlsInstance = null;
  }

  const isHls = videoUrl.includes('.m3u8');
  if (isHls && window.Hls && Hls.isSupported()) {
    video.innerHTML = '';
    cinemaHlsInstance = new Hls({
      enableWorker: true,
      lowLatencyMode: true,
    });
    cinemaHlsInstance.loadSource(videoUrl);
    cinemaHlsInstance.attachMedia(video);
    cinemaHlsInstance.on(Hls.Events.ERROR, function(event, data) {
      if (data.fatal) {
        console.warn("HLS fatal error, trying recover:", data);
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            cinemaHlsInstance.startLoad();
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            cinemaHlsInstance.recoverMediaError();
            break;
          default:
            cinemaHlsInstance.destroy();
            break;
        }
      }
    });
  } else {
    video.innerHTML = `<source src="${videoUrl}" type="${isHls ? 'application/x-mpegURL' : 'video/mp4'}"/>`;
  }

  tracks.forEach(track => {
    const trackEl = document.createElement('track');
    trackEl.kind = 'subtitles';
    trackEl.label = track.label;
    trackEl.srclang = track.srclang;
    trackEl.src = track.src;
    if (track.default) trackEl.setAttribute('default', '');
    video.appendChild(trackEl);
  });
  video.load();

  if (window.Plyr) {
    if (!cinemaPlyrInstance) {
      cinemaPlyrInstance = new Plyr('#cinema-player', {
        controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'fullscreen'],
        captions: { active: true, update: true, language: 'fr' }
      });
    } else {
      if (!isHls) {
        cinemaPlyrInstance.source = { type: 'video', sources: [{ src: videoUrl, type: 'video/mp4' }], tracks };
      }
    }
    cinemaPlyrInstance.play().catch(() => {});
  } else {
    video.play().catch(() => {});
  }
}

function closeCinemaPlayer() {
  const modal = document.getElementById('cinema-modal');
  if (modal) modal.classList.remove('open');
  if (cinemaPlyrInstance) cinemaPlyrInstance.pause();
  if (cinemaHlsInstance) {
    cinemaHlsInstance.destroy();
    cinemaHlsInstance = null;
  }
  const video = document.getElementById('cinema-player');
  if (video) video.pause();
}

function playAdjacentEpisode(direction) {
  if (!currentPlayingEpNum) return;
  const targetNum = parseInt(currentPlayingEpNum, 10) + direction;
  const targetRow = document.querySelector(`.episode-item[data-num="${targetNum}"]`);
  if (targetRow) {
    const playBtn = targetRow.querySelector('.btn-play-ep');
    if (playBtn) playEpisode(playBtn);
  } else {
    showToast(`Aucun épisode trouvé (${direction > 0 ? 'suivant' : 'précédent'})`, 'info');
  }
}

function closePlayer() {
  document.getElementById('player-section')?.style.setProperty('display', 'none');
  if (plyrInstance) plyrInstance.pause();
  closeCinemaPlayer();
}

async function toggleFavorite(btn) {
  const url = btn.dataset.url;
  const title = btn.dataset.title;
  const imageUrl = btn.dataset.image || '';
  const source = btn.dataset.source || 'french-manga';
  const active = btn.classList.contains('active');

  try {
    if (active) {
      await fetch('/api/favorites', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      btn.classList.remove('active');
      btn.querySelector('span').textContent = 'Ajouter a la bibliotheque';
      showToast('Retire de la bibliotheque', 'info');
    } else {
      await fetch('/api/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, title, imageUrl, source })
      });
      btn.classList.add('active');
      btn.querySelector('span').textContent = 'Dans la bibliotheque';
      showToast('Ajoute a la bibliotheque', 'success');
    }
  } catch (error) {
    showToast('Erreur favoris', 'error');
  }
}

async function checkFavoriteStatus() {
  const favBtn = document.getElementById('fav-btn');
  if (!favBtn) return;
  try {
    const resp = await fetch('/api/favorites/check?url=' + encodeURIComponent(favBtn.dataset.url));
    const data = await resp.json();
    if (data.isFavorite) {
      favBtn.classList.add('active');
      favBtn.querySelector('span').textContent = 'Dans la bibliotheque';
    }
  } catch (error) {}
}

async function toggleAutoDownload(input) {
  try {
    await fetch('/api/favorites/auto-download', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: input.dataset.url, autoDownload: input.checked })
    });
    showToast(input.checked ? 'Auto-DL active' : 'Auto-DL desactive', 'info');
  } catch (error) {
    showToast('Erreur Auto-DL', 'error');
  }
}

async function toggleAutoDownloadFromLibrary(input) {
  await toggleAutoDownload(input);
}

async function removeFavorite(btn) {
  if (!confirm('Retirer de la bibliotheque ?')) return;
  try {
    await fetch('/api/favorites', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: btn.dataset.url })
    });
    btn.closest('.anime-card')?.remove();
    showToast('Retire de la bibliotheque', 'info');
  } catch (error) {
    showToast('Erreur', 'error');
  }
}

function initSSE() {
  if (sseSource) sseSource.close();
  sseSource = new EventSource('/api/download/stream');
  sseSource.addEventListener('download-update', event => {
    try { updateTaskRow(JSON.parse(event.data)); } catch (error) {}
  });
  sseSource.onerror = () => setTimeout(initSSE, 3000);
}

function getTaskCategory(status) {
  if (['DOWNLOADING', 'RETRYING', 'PAUSED', 'MUXING'].includes(status)) return 'active';
  if (['PENDING', 'SCHEDULED'].includes(status)) return 'queue';
  return 'done';
}

function renderTaskRowInner(task, queueIndex = 1) {
  const cat = getTaskCategory(task.status);
  const animeName = task.animeName || 'Anime';
  const initial = (animeName.trim().charAt(0) || 'A').toUpperCase();
  const epNum = (task.episodeNumber !== undefined && task.episodeNumber !== null && task.episodeNumber !== '' && String(task.episodeNumber) !== 'undefined') ? task.episodeNumber : '';
  const subtitle = 'Épisode ' + epNum + (task.fileName ? ' - ' + task.fileName : '');
  const progress = Number(task.progress || 0);

  if (cat === 'queue') {
    let sizeContent = escapeHtml(task.totalSize || '0 B');
    if (task.status === 'SCHEDULED' && task.scheduledStartTime) {
      sizeContent = `<span class="dl-scheduled-info" data-time="${escapeHtml(task.scheduledStartTime)}">Planifié : ${formatScheduledTime(task.scheduledStartTime)}</span>`;
    }
    return `
      <span class="queue-index">${queueIndex}</span>
      <span class="drag-dots">::</span>
      <div class="dl-main">
        <div class="dl-cover">${escapeHtml(initial)}</div>
        <div>
          <span class="dl-task-name">${escapeHtml(animeName)}</span>
          <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
        </div>
      </div>
      <span class="dl-size">${sizeContent}</span>
      <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
        ${renderTaskActions(task)}
      </div>`;
  }

  if (cat === 'done') {
    const vStatus = task.verificationStatus || 'UNVERIFIED';
    let verifBadge = '';
    if (vStatus === 'VALID') {
      const dur = task.formattedDuration ? ` • ${task.formattedDuration}` : '';
      verifBadge = `<span class="status-badge dl-verif-badge badge-ok" style="font-size:10px; padding: 2px 6px;" title="Fichier intègre et lisible sur le disque">✓ Valide${escapeHtml(dur)}</span>`;
    } else if (vStatus === 'MISSING') {
      verifBadge = `<span class="status-badge dl-verif-badge badge-err" style="font-size:10px; padding: 2px 6px;" title="${escapeHtml(task.verificationError || 'Fichier introuvable sur le disque')}">⚠ Manquant</span>`;
    } else if (vStatus === 'CORRUPTED') {
      verifBadge = `<span class="status-badge dl-verif-badge badge-err" style="font-size:10px; padding: 2px 6px;" title="${escapeHtml(task.verificationError || 'Fichier vidéo corrompu')}">✗ Corrompu</span>`;
    } else if (vStatus === 'EMPTY') {
      verifBadge = `<span class="status-badge dl-verif-badge badge-err" style="font-size:10px; padding: 2px 6px;" title="Fichier de 0 octet">✗ Vide</span>`;
    } else {
      verifBadge = `<span class="status-badge dl-verif-badge badge-other" style="font-size:10px; padding: 2px 6px;" title="Non vérifié">Non vérifié</span>`;
    }

    return `
      <div class="dl-main">
        <div class="dl-cover">${escapeHtml(initial)}</div>
        <div>
          <span class="dl-task-name">${escapeHtml(animeName)}</span>
          <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
        </div>
      </div>
      <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-start;">
        <span class="status-badge dl-task-status ${statusClass(task.status)}">
          ${translateStatus(task.status)}
        </span>
        ${verifBadge}
      </div>
      <span class="dl-size">${escapeHtml(task.totalSize || '0 B')}</span>
      <span class="dl-progress-text">${progress.toFixed(1)}%</span>
      <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-verification="${escapeHtml(vStatus)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
        ${renderTaskActions(task)}
      </div>`;
  }

  // cat === 'active'
  let etaText = '';
  if (task.status === 'DOWNLOADING') {
    const total = task.totalBytes || 0;
    const dl = task.downloadedBytes || 0;
    const sp = task.speedBytes || parseSpeedToBytes(task.speed);
    if (total > dl && sp > 0) {
      etaText = '• ' + formatEta(Math.round((total - dl) / sp));
    }
  }

  const limitKb = task.maxSpeedLimit > 0 ? Math.round(task.maxSpeedLimit / 1024) : 0;
  const safeId = escapeHtml(task.id);
  const limitHtml = limitKb > 0
    ? `<span class="dl-speed-limit-badge">Max: ${limitKb} KB/s <button class="speed-limit-btn" onclick="changeTaskSpeedLimit('${safeId}')">Modifier</button></span>`
    : `<button class="speed-limit-btn" onclick="changeTaskSpeedLimit('${safeId}')">Limiter</button>`;

  return `
    <div class="dl-main">
      <div class="dl-cover">${escapeHtml(initial)}</div>
      <div>
        <span class="dl-task-name">${escapeHtml(animeName)}</span>
        <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
      </div>
    </div>
    <div class="dl-progress-wrap">
      <div class="dl-progress-bar">
        <div class="dl-progress-fill" style="width:${progress}%"></div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span class="dl-size">${escapeHtml(task.downloadedSize || '0 B')} / ${escapeHtml(task.totalSize || '0 B')}</span>
        <span class="dl-eta" id="eta-${escapeHtml(task.id)}">${etaText}</span>
      </div>
    </div>
    <span class="dl-progress-text">${progress.toFixed(1)}%</span>
    <div class="dl-speed-col">
      <span class="dl-speed">${escapeHtml(task.speed || '')}</span>
      <span class="dl-error">${escapeHtml(task.error || '')}</span>
      <div class="dl-speed-limit-container" style="margin-top: 0.25rem;">
        ${limitHtml}
      </div>
    </div>
    <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
      ${renderTaskActions(task)}
    </div>`;
}

function createTaskRow(task) {
  const row = document.createElement('div');
  const cat = getTaskCategory(task.status);
  row.className = 'dl-task-row' + (cat === 'queue' ? ' queue-row' : (cat === 'done' ? ' completed-row' : ''));
  row.id = 'task-' + task.id;
  row.dataset.id = task.id;
  row.dataset.category = cat;
  row.dataset.status = task.status;
  if (cat === 'queue') row.setAttribute('draggable', 'true');
  row.innerHTML = renderTaskRowInner(task);
  return row;
}

function updateTaskRow(task) {
  let row = document.getElementById('task-' + task.id);
  const newCat = getTaskCategory(task.status);
  const targetParentId = newCat === 'active' ? 'download-list' : (newCat === 'queue' ? 'queue-list' : 'completed-list');
  const targetParent = document.getElementById(targetParentId);
  if (!targetParent) return;

  if (!row) {
    row = createTaskRow(task);
    if (newCat === 'done') {
      targetParent.prepend(row);
    } else {
      targetParent.appendChild(row);
    }
    if (newCat === 'queue') reindexQueueRows();
    refreshDownloadStats();
    refreshDownloadBadge();
    return;
  }

  const oldCat = row.dataset.category || (row.classList.contains('queue-row') ? 'queue' : (row.classList.contains('completed-row') ? 'done' : 'active'));
  if (oldCat !== newCat) {
    row.dataset.category = newCat;
    row.dataset.status = task.status;
    row.className = 'dl-task-row' + (newCat === 'queue' ? ' queue-row' : (newCat === 'done' ? ' completed-row' : ''));
    if (newCat === 'queue') {
      row.setAttribute('draggable', 'true');
      targetParent.appendChild(row);
    } else {
      row.removeAttribute('draggable');
      if (newCat === 'done') {
        targetParent.prepend(row);
      } else {
        targetParent.appendChild(row);
      }
    }
    row.innerHTML = renderTaskRowInner(task);
    reindexQueueRows();
    refreshDownloadStats();
    refreshDownloadBadge();
    return;
  }

  // In-place micro updates when category is unchanged
  row.dataset.status = task.status;
  if (newCat === 'active') {
    const fill = row.querySelector('.dl-progress-fill');
    if (fill) fill.style.width = (task.progress || 0) + '%';

    const text = row.querySelector('.dl-progress-text');
    if (text) text.textContent = Number(task.progress || 0).toFixed(1) + '%';

    const size = row.querySelector('.dl-size');
    if (size) size.textContent = (task.downloadedSize || '0 B') + ' / ' + (task.totalSize || '0 B');

    let etaEl = row.querySelector('.dl-eta');
    if (task.status === 'DOWNLOADING') {
      const total = task.totalBytes || 0;
      const dl = task.downloadedBytes || 0;
      const sp = task.speedBytes || parseSpeedToBytes(task.speed);
      if (etaEl) {
        if (total > dl && sp > 0) {
          etaEl.textContent = '• ' + formatEta(Math.round((total - dl) / sp));
        } else {
          etaEl.textContent = '';
        }
      }
    } else if (etaEl) {
      etaEl.textContent = '';
    }

    const speed = row.querySelector('.dl-speed');
    if (speed) speed.textContent = task.speed || '';

    const error = row.querySelector('.dl-error');
    if (error) error.textContent = task.error || '';

    const actEl = row.querySelector('.dl-task-actions');
    if (actEl && actEl.dataset.status !== task.status) {
      actEl.dataset.status = task.status;
      actEl.innerHTML = renderTaskActions(task);
    }
  } else if (newCat === 'queue') {
    const size = row.querySelector('.dl-size');
    if (size) {
      if (task.status === 'SCHEDULED' && task.scheduledStartTime) {
        size.innerHTML = `<span class="dl-scheduled-info" data-time="${task.scheduledStartTime}">Planifié : ${formatScheduledTime(task.scheduledStartTime)}</span>`;
      } else {
        size.textContent = task.totalSize || '0 B';
      }
    }
    const actEl = row.querySelector('.dl-task-actions');
    if (actEl && actEl.dataset.status !== task.status) {
      actEl.dataset.status = task.status;
      actEl.innerHTML = renderTaskActions(task);
    }
  } else if (newCat === 'done') {
    const badge = row.querySelector('.dl-task-status');
    if (badge) {
      badge.textContent = translateStatus(task.status);
      badge.className = 'status-badge dl-task-status ' + statusClass(task.status);
    }
    const actEl = row.querySelector('.dl-task-actions');
    if (actEl && actEl.dataset.status !== task.status) {
      actEl.dataset.status = task.status;
      actEl.innerHTML = renderTaskActions(task);
    }
  }

  refreshDownloadStats();
}

function renderTaskActions(task) {
  const id = task.id;
  const animeName = task.animeName || '';
  const safeAnime = animeName.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
  const epNum = (task.episodeNumber !== undefined && task.episodeNumber !== null && task.episodeNumber !== '' && String(task.episodeNumber) !== 'undefined') ? `'${task.episodeNumber}'` : 'null';
  const upIcon = '<svg viewBox="0 0 24 24"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';
  const downIcon = '<svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>';
  const pauseIcon = '<svg viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></svg>';
  const playIcon = '<svg viewBox="0 0 24 24"><path d="M7 4v16l13-8Z"/></svg>';
  const xIcon = '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  const trashIcon = '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/></svg>';
  const retryIcon = '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>';
  const shieldIcon = '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>';

  if (task.status === 'DOWNLOADING' || task.status === 'RETRYING' || task.status === 'MUXING') {
    return `<button class="btn btn-icon" title="Pause" onclick="apiPost('/api/download/${id}/pause')">${pauseIcon}</button>
            <button class="btn btn-icon btn-danger" title="Annuler" onclick="cancelTask('${id}')">${xIcon}</button>`;
  }
  if (task.status === 'PAUSED') {
    return `<button class="btn btn-icon btn-primary" title="Reprendre" onclick="apiPost('/api/download/${id}/resume')">${playIcon}</button>
            <button class="btn btn-icon btn-danger" title="Annuler" onclick="cancelTask('${id}')">${xIcon}</button>`;
  }
  if (task.status === 'PENDING' || task.status === 'SCHEDULED') {
    return `<button class="btn btn-icon" title="Monter" onclick="moveTaskToTop('${id}')">${upIcon}</button>
            <button class="btn btn-icon" title="Descendre" disabled>${downIcon}</button>
            ${animeName ? `<button class="btn btn-icon" title="Prioriser la série" onclick="moveSeriesToTop(\`${safeAnime}\`)"><svg viewBox="0 0 24 24"><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg></button>` : ''}
            <button class="btn btn-icon btn-danger" title="Annuler" onclick="cancelTask('${id}')">${xIcon}</button>`;
  }
  if (task.status === 'FAILED' || task.status === 'CANCELLED') {
    const hasProgress = (task.downloadedBytes && task.downloadedBytes > 0) || (task.progress && task.progress > 0);
    return `${hasProgress ? `<button class="btn btn-icon btn-success" title="Reprendre le téléchargement" onclick="apiPost('/api/download/${id}/resume')">${playIcon}</button>` : ''}
            <button class="btn btn-icon btn-primary" title="Re-télécharger / Réessayer" onclick="redownloadTask('${id}')">${retryIcon}</button>
            <button class="btn btn-icon" title="Vérifier l'intégrité" onclick="verifyTask('${id}', this)">${shieldIcon}</button>
            <button class="btn btn-icon" title="Retirer" onclick="removeTask('${id}')">${trashIcon}</button>`;
  }
  if (task.status === 'COMPLETED') {
    const isProblem = ['MISSING', 'CORRUPTED', 'EMPTY'].includes(task.verificationStatus);
    return `<button class="btn btn-icon btn-primary" title="Lire" onclick="playDownloadedTask('${id}', \`${safeAnime}\`, ${epNum})">${playIcon}</button>
            <button class="btn btn-icon" title="Vérifier l'intégrité" onclick="verifyTask('${id}', this)">${shieldIcon}</button>
            ${isProblem ? `<button class="btn btn-icon btn-primary" title="Re-télécharger cet épisode" onclick="redownloadTask('${id}')">${retryIcon}</button>` : ''}
            <button class="btn btn-icon" title="Retirer" onclick="removeTask('${id}')">${trashIcon}</button>`;
  }
  return '';
}

function translateStatus(status) {
  const labels = {
    PENDING: 'En attente',
    SCHEDULED: 'Planifié',
    DOWNLOADING: 'Téléchargement',
    RETRYING: 'Nouvelle tentative',
    PAUSED: 'Pause',
    COMPLETED: 'Terminé',
    FAILED: 'Échec',
    CANCELLED: 'Annulé',
    MUXING: 'Muxing sous-titres'
  };
  return labels[status] || status;
}

function statusClass(status) {
  if (status === 'COMPLETED') return 'badge-ok';
  if (status === 'FAILED' || status === 'CANCELLED') return 'badge-err';
  if (status === 'MUXING') return 'badge-warn';
  return 'badge-other';
}

async function apiPost(url, body) {
  try {
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined
    });
    setTimeout(refreshDownloadStats, 250);
  } catch (e) {
    showToast('Erreur lors de l\'action', 'error');
  }
}

async function cancelTask(id) {
  try {
    const res = await fetch('/api/download/' + id, { method: 'DELETE' });
    if (res.ok) {
      showToast('Téléchargement annulé', 'info');
    }
    setTimeout(refreshDownloadStats, 250);
  } catch (e) {
    showToast('Erreur lors de l\'annulation', 'error');
  }
}

async function removeTask(id) {
  try {
    await fetch('/api/download/' + id + '/remove', { method: 'DELETE' });
    document.getElementById('task-' + id)?.remove();
    reindexQueueRows();
    refreshDownloadStats();
    refreshDownloadBadge();
    showToast('Tâche retirée', 'info');
  } catch (e) {
    showToast('Erreur de suppression', 'error');
  }
}

async function moveTaskToTop(id) {
  try {
    const resp = await fetch('/api/download/' + id + '/move-to-top', { method: 'POST' });
    const data = await resp.json();
    showToast(data.message || 'Priorité mise à jour', data.success ? 'success' : 'error');
    if (data.success) setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    showToast('Erreur réseau', 'error');
  }
}

async function moveSeriesToTop(animeName) {
  try {
    const resp = await fetch('/api/download/move-series-to-top', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animeName })
    });
    const data = await resp.json();
    showToast(data.message || 'Série priorisée', data.success ? 'success' : 'error');
    if (data.success) setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    showToast('Erreur réseau', 'error');
  }
}

function filterDownloadView(btn) {
  document.querySelectorAll('[data-download-filter]').forEach(item => item.classList.remove('active'));
  btn.classList.add('active');
  const filter = btn.dataset.downloadFilter;
  document.querySelectorAll('[data-download-group]').forEach(group => {
    group.style.display = (filter === 'all' || group.dataset.downloadGroup === filter) ? '' : 'none';
  });
  refreshDownloadStats();
}

function formatBytesSpeed(bytes) {
  if (!bytes || bytes <= 0) return '0 B/s';
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

function refreshDownloadStats() {
  const activeRows = document.querySelectorAll('#download-list .dl-task-row');
  const queueRows = document.querySelectorAll('#queue-list .dl-task-row');
  const doneRows = document.querySelectorAll('#completed-list .dl-task-row');

  const activeCount = activeRows.length;
  const queuedCount = queueRows.length;
  const doneCount = doneRows.length;
  const totalCount = activeCount + queuedCount + doneCount;

  // Aggregate speed across active rows
  let totalSpeedBytes = 0;
  activeRows.forEach(row => {
    const sp = row.querySelector('.dl-speed')?.textContent.trim();
    if (sp) totalSpeedBytes += parseSpeedToBytes(sp);
  });

  setText('stat-active', activeCount);
  setText('stat-queued', queuedCount);
  setText('stat-speed', formatBytesSpeed(totalSpeedBytes));
  setText('download-count-badge', activeCount + queuedCount);
  setText('mob-download-badge', activeCount + queuedCount);

  // Tab badges
  setText('tab-badge-queue', activeCount + queuedCount);
  setText('tab-badge-done', doneCount);
  setText('tab-badge-all', totalCount);

  // Empty state placeholders
  const activeEmptyNote = document.getElementById('active-empty-note');
  const queueEmptyNote = document.getElementById('queue-empty-note');
  const doneEmptyNote = document.getElementById('done-empty-note');
  const globalEmpty = document.getElementById('dl-empty');
  const downloadHint = document.querySelector('.download-hint');

  if (activeEmptyNote) activeEmptyNote.style.display = activeCount === 0 ? 'block' : 'none';
  if (queueEmptyNote) queueEmptyNote.style.display = queuedCount === 0 ? 'block' : 'none';
  if (doneEmptyNote) doneEmptyNote.style.display = doneCount === 0 ? 'block' : 'none';

  if (globalEmpty) {
    globalEmpty.style.display = totalCount === 0 ? 'flex' : 'none';
  }

  if (downloadHint) {
    const activeFilter = document.querySelector('.tab-btn.active')?.dataset.downloadFilter || 'queue';
    downloadHint.style.display = (activeFilter !== 'done' && queuedCount > 1) ? 'flex' : 'none';
  }
}

function refreshDownloadBadge() {
  const desktopBadge = document.getElementById('download-count-badge');
  const mobBadge = document.getElementById('mob-download-badge');
  fetch('/api/download/status')
    .then(r => r.json())
    .then(tasks => {
      const activeOrPending = tasks.filter(task => ['DOWNLOADING', 'RETRYING', 'PENDING', 'SCHEDULED', 'PAUSED', 'MUXING'].includes(task.status));
      const count = activeOrPending.length;
      if (desktopBadge) setText('download-count-badge', count);
      if (mobBadge) setText('mob-download-badge', count);

      if (document.getElementById('episode-list') && typeof ANIME_NAME !== 'undefined') {
        const currentAnimeTasks = activeOrPending.filter(t => t.animeName === ANIME_NAME);
        currentAnimeTasks.forEach(task => {
          const row = document.querySelector(`.episode-item[data-num="${task.episodeNumber}"]`);
          if (row && !row.querySelector('.ep-queued-badge') && !row.querySelector('.ep-done-badge')) {
            const badge = document.createElement('span');
            badge.className = 'ep-queued-badge';
            badge.textContent = task.status === 'DOWNLOADING' ? 'En cours' : 'En file d\'attente';
            const titleEl = row.querySelector('.episode-title');
            if (titleEl) {
              titleEl.after(badge);
            } else {
              row.appendChild(badge);
            }
          }
        });
      }
    })
    .catch(() => {});
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function sanitizeFilename(name) {
  return name.replace(/[<>:"/\\|?*]/g, '_').replace(/\s+/g, ' ').trim();
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Drag and Drop support
function initDragAndDrop() {
  const queueList = document.getElementById('queue-list');
  if (!queueList) return;

  let dragEl = null;

  queueList.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.queue-row');
    if (!row) return;
    dragEl = row;
    e.dataTransfer.effectAllowed = 'move';
    row.classList.add('dragging');
  });

  queueList.addEventListener('dragover', (e) => {
    e.preventDefault();
    const row = e.target.closest('.queue-row');
    if (!row || row === dragEl) return;
    
    const bounding = row.getBoundingClientRect();
    const offset = e.clientY - bounding.top;
    if (offset > bounding.height / 2) {
      row.after(dragEl);
    } else {
      row.before(dragEl);
    }
  });

  queueList.addEventListener('dragend', async (e) => {
    const row = e.target.closest('.queue-row');
    if (row) row.classList.remove('dragging');
    dragEl = null;

    reindexQueueRows();

    const orderedIds = [...queueList.querySelectorAll('.queue-row')].map(r => r.dataset.id);
    
    try {
      const resp = await fetch('/api/download/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(orderedIds)
      });
      const data = await resp.json();
      if (data.success) {
        showToast('File d\'attente réorganisée', 'success');
      } else {
        showToast(data.error || 'Erreur lors du réordonnancement', 'error');
      }
    } catch (err) {
      showToast('Erreur de connexion', 'error');
    }
  });
}

function reindexQueueRows() {
  const queueList = document.getElementById('queue-list');
  if (!queueList) return;
  queueList.querySelectorAll('.queue-row').forEach((row, idx) => {
    const idxEl = row.querySelector('.queue-index');
    if (idxEl) idxEl.textContent = idx + 1;
  });
}

// Speed limit change
async function changeTaskSpeedLimit(id) {
  const currentLimitStr = prompt("Vitesse maximale pour cette tâche en KB/s (0 pour illimitée) :");
  if (currentLimitStr === null) return;

  const limitKb = parseInt(currentLimitStr, 10);
  if (isNaN(limitKb) || limitKb < 0) {
    showToast("Vitesse invalide", "error");
    return;
  }

  const limitBytes = limitKb * 1024;
  try {
    const resp = await fetch(`/api/download/${id}/speed-limit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: limitBytes })
    });
    const data = await resp.json();
    if (data.success) {
      showToast("Limite de vitesse mise à jour", "success");
    } else {
      showToast(data.error || "Erreur", "error");
    }
  } catch (err) {
    showToast("Erreur de connexion", "error");
  }
}

// Scheduled count down
function formatScheduledTime(isoString) {
  try {
    const target = new Date(isoString);
    const now = new Date();
    const diffMs = target - now;
    if (diffMs <= 0) return "Démarrage imminent...";
    
    const diffSecs = Math.floor(diffMs / 1000);
    const hours = Math.floor(diffSecs / 3600);
    const mins = Math.floor((diffSecs % 3600) / 60);
    const secs = diffSecs % 60;
    
    let parts = [];
    if (hours > 0) parts.push(hours + "h");
    if (mins > 0 || hours > 0) parts.push(mins + "m");
    parts.push(secs + "s");
    
    const timeFormatted = target.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `Démarre à ${timeFormatted} (dans ${parts.join(' ')})`;
  } catch (e) {
    return isoString;
  }
}

function initScheduledTicker() {
  setInterval(() => {
    document.querySelectorAll('.dl-scheduled-info[data-time]').forEach(el => {
      el.textContent = formatScheduledTime(el.dataset.time);
    });
  }, 1000);
}

// Delegated listener for Thymeleaf-rendered play buttons (data-action="play")
function bindPlayActionButtons() {
  document.addEventListener('click', (e) => {
    // Play button
    const playBtn = e.target.closest('[data-action="play"]');
    if (playBtn) {
      const taskId = playBtn.dataset.taskId;
      if (taskId) playDownloadedTask(taskId);
      return;
    }
    // Delete history entry button
    const delBtn = e.target.closest('[data-action="delete-history"]');
    if (delBtn) {
      const taskId = delBtn.dataset.taskId;
      if (taskId) deleteHistoryEntry(taskId, delBtn);
      return;
    }
    // Verify history entry button
    const verifBtn = e.target.closest('[data-action="verify"]');
    if (verifBtn) {
      const taskId = verifBtn.dataset.taskId;
      if (taskId) verifyTask(taskId, verifBtn);
      return;
    }
    // Redownload history entry button
    const redlBtn = e.target.closest('[data-action="redownload"]');
    if (redlBtn) {
      const taskId = redlBtn.dataset.taskId;
      if (taskId) redownloadTask(taskId);
      return;
    }
  });
}

// =========================================================================
// Nettoyage historique & bibliothèque
// =========================================================================

async function deleteHistoryEntry(taskId, triggerEl) {
  try {
    const resp = await fetch('/api/history/' + taskId, { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) {
      // Retire la ligne du DOM (table row ou history-item)
      const row = triggerEl?.closest('tr') || triggerEl?.closest('.history-item');
      row?.remove();
      showToast('Entree supprimee', 'success');
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

async function clearHistory(statusFilter) {
  const msg = statusFilter
    ? 'Supprimer toutes les entrees avec ce statut ?'
    : 'Vider completement l\'historique ? Cette action est irreversible.';
  if (!confirm(msg)) return;

  let url = '/api/history';
  if (statusFilter) url += '?status=' + encodeURIComponent(statusFilter);

  try {
    const resp = await fetch(url, { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message || 'Historique vide', 'success');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

async function clearHistoryByStatus(statuses) {
  await clearHistory(statuses);
}

async function clearAllFavorites() {
  if (!confirm('Retirer tous les favoris de la bibliotheque ? Cette action est irreversible.')) return;
  try {
    const resp = await fetch('/api/favorites/all', { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message || 'Bibliotheque videe', 'success');
      const grid = document.getElementById('favorites-grid');
      if (grid) grid.innerHTML = '';
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

// Direct play from downloads or history page
async function playDownloadedTask(taskId, animeName, episodeNumber) {
  showToast('Résolution du flux vidéo local...', 'info');
  try {
    const videoUrl = '/api/media/stream/' + taskId;
    const subsResp = await fetch('/api/media/subtitles/' + taskId);
    let tracks = [];
    try {
      const subs = await subsResp.json();
      tracks = subs.map(sub => ({ kind: 'captions', label: sub.label, srclang: sub.srclang, src: sub.src, default: sub.srclang === 'fr' }));
    } catch (e) {
      console.log("No subtitles found or error fetching subs", e);
    }

    const epDisplay = (episodeNumber && String(episodeNumber) !== 'null' && String(episodeNumber) !== 'undefined') ? ` - Épisode ${episodeNumber}` : '';
    const title = animeName ? `${animeName}${epDisplay}` : 'Lecture vidéo';
    const cinemaModal = document.getElementById('cinema-modal');
    if (cinemaModal) {
      openCinemaModal(videoUrl, title, tracks, episodeNumber, { isDownloaded: true, serverType: 'Disque dur (Local)' });
    } else {
      const playerSection = document.getElementById('player-section');
      const video = document.getElementById('plyr-player');
      if (!playerSection || !video) return;

      video.innerHTML = `<source src="${videoUrl}" type="video/mp4"/>`;
      tracks.forEach(track => {
        const trackEl = document.createElement('track');
        trackEl.kind = 'subtitles';
        trackEl.label = track.label;
        trackEl.srclang = track.srclang;
        trackEl.src = track.src;
        if (track.default) trackEl.setAttribute('default', '');
        video.appendChild(trackEl);
      });
      video.load();
      playerSection.style.display = 'block';
      playerSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

      if (window.Plyr) {
        if (!plyrInstance) {
          plyrInstance = new Plyr('#plyr-player', {
            controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'fullscreen'],
            captions: { active: true, update: true, language: 'fr' }
          });
        } else {
          plyrInstance.source = { type: 'video', sources: [{ src: videoUrl, type: 'video/mp4' }], tracks };
        }
        plyrInstance.play();
      } else {
        video.play();
      }
    }
  } catch (error) {
    showToast('Erreur lecteur: ' + error.message, 'error');
  }
}



// =========================================================================
// Raccourcis clavier globaux
// =========================================================================

function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

    if (e.key === 'Escape') {
      closeCinemaPlayer();
      document.getElementById('settings-panel')?.classList.remove('open');
      document.querySelectorAll('.search-autocomplete-dropdown').forEach(d => d.classList.remove('open'));
      document.getElementById('quality-modal')?.style.setProperty('display', 'none');
      document.getElementById('subtitle-modal')?.style.setProperty('display', 'none');
      return;
    }

    if (isInput) return;

    // Ctrl + K ou Cmd + K : Focus recherche
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const input = document.getElementById('topbar-search-input') || document.getElementById('search-input');
      if (input) {
        input.focus();
        input.select();
      }
    } else if (e.key === '/' && !isInput) {
      e.preventDefault();
      const input = document.getElementById('topbar-search-input') || document.getElementById('search-input');
      if (input) {
        input.focus();
        input.select();
      }
    } else if (e.key.toLowerCase() === 't' && !isInput) {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(current === 'dark' ? 'light' : 'dark');
      showToast(`Thème basculé : ${current === 'dark' ? 'Clair' : 'Sombre'}`, 'info');
    }
  });
}

// =========================================================================
// Autocomplétion de recherche en direct
// =========================================================================

function initSearchAutocomplete() {
  const formatProxyImage = (url) => {
    if (!url) return '';
    if ((url.includes('voir-anime') || url.includes('voembed') || url.includes('vidmoly')) && !url.startsWith('/api/media/image-proxy')) {
      return `/api/media/image-proxy?url=${encodeURIComponent(url)}`;
    }
    return url;
  };

  const bindInput = (inputId, dropdownId, getSource) => {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!input || !dropdown) return;

    let debounceTimer = null;
    let selectedIndex = -1;

    const updateSelection = (items) => {
      items.forEach((item, idx) => {
        if (idx === selectedIndex) {
          item.classList.add('selected');
          item.scrollIntoView({ block: 'nearest' });
        } else {
          item.classList.remove('selected');
        }
      });
    };

    input.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      selectedIndex = -1;
      const query = input.value.trim();
      if (query.length < 2) {
        dropdown.innerHTML = '';
        dropdown.classList.remove('open');
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const source = getSource();
          const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}&source=${encodeURIComponent(source)}`);
          if (!resp.ok) return;
          const results = await resp.json();
          if (!results || results.length === 0) {
            dropdown.innerHTML = '<div style="padding:16px;color:var(--muted);font-size:13px;text-align:center;">Aucun résultat trouvé pour "' + escapeHtml(query) + '"</div>';
            dropdown.classList.add('open');
            return;
          }
          dropdown.innerHTML = results.slice(0, 6).map(item => {
            const imgUrl = formatProxyImage(item.imageUrl);
            const posterHtml = imgUrl ? `
              <img class="autocomplete-poster" src="${imgUrl}" alt="" loading="lazy"
                   onerror="this.style.display='none';this.nextElementSibling.style.display='flex';"/>
              <div class="autocomplete-poster-placeholder" style="display:none;">🎬</div>
            ` : `
              <div class="autocomplete-poster-placeholder">🎬</div>
            `;

            const versionBadge = item.version ? `
              <span class="autocomplete-badge ${item.version.toUpperCase() === 'VF' ? 'autocomplete-badge-vf' : 'autocomplete-badge-vostfr'}">${escapeHtml(item.version)}</span>
            ` : '';

            return `
              <a href="/anime?url=${encodeURIComponent(item.url)}&source=${encodeURIComponent(source)}" class="autocomplete-item">
                ${posterHtml}
                <div class="autocomplete-info">
                  <div class="autocomplete-title">${escapeHtml(item.title)}</div>
                  <div class="autocomplete-sub">
                    <span>${escapeHtml(item.type || 'Anime')}</span>
                    ${versionBadge}
                    ${item.episodeInfo ? `<span>• ${escapeHtml(item.episodeInfo)}</span>` : ''}
                  </div>
                </div>
              </a>
            `;
          }).join('');
          dropdown.classList.add('open');
        } catch (e) {}
      }, 220);
    });

    input.addEventListener('keydown', (e) => {
      if (!dropdown.classList.contains('open')) return;
      const items = Array.from(dropdown.querySelectorAll('.autocomplete-item'));
      if (items.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % items.length;
        updateSelection(items);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        updateSelection(items);
      } else if (e.key === 'Enter' && selectedIndex >= 0 && items[selectedIndex]) {
        e.preventDefault();
        items[selectedIndex].click();
      } else if (e.key === 'Escape') {
        dropdown.classList.remove('open');
      }
    });

    document.addEventListener('click', (e) => {
      if (!input.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.classList.remove('open');
      }
    });
  };

  bindInput('topbar-search-input', 'topbar-search-dropdown', () => {
    return document.getElementById('topbar-search-source')?.value || 'french-manga';
  });

  bindInput('search-input', 'hero-search-dropdown', () => {
    const checkedRadio = document.querySelector('input[name="source"]:checked');
    return checkedRadio?.value || 'french-manga';
  });

  // Synchronisation dynamique du changement de source
  document.querySelectorAll('input[name="source"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      const topbarSource = document.getElementById('topbar-search-source');
      if (topbarSource) topbarSource.value = e.target.value;

      // Si du texte est déjà saisi, relancer instantanément l'autocomplétion
      const heroInput = document.getElementById('search-input');
      if (heroInput && heroInput.value.trim().length >= 2) {
        heroInput.dispatchEvent(new Event('input'));
      }
    });
  });
}

// =========================================================================
// Pagination par tranches d'épisodes et filtres de sélection par lot
// =========================================================================

function initEpisodeRangePagination() {
  const list = document.getElementById('episode-list');
  const bar = document.getElementById('episode-range-bar');
  if (!list || !bar) return;

  const items = Array.from(list.querySelectorAll('.episode-item'));
  if (items.length <= 40) {
    bar.style.display = 'none';
  } else {
    const nums = items.map(el => parseInt(el.dataset.num, 10)).filter(n => !isNaN(n));
    if (nums.length > 0) {
      const minNum = Math.min(...nums);
      const maxNum = Math.max(...nums);

      bar.innerHTML = '';
      const rangeSize = 50;

      const allChip = document.createElement('button');
      allChip.type = 'button';
      allChip.className = 'episode-range-chip active';
      allChip.textContent = `Tous (${items.length})`;
      allChip.onclick = () => filterEpisodeRange('all', allChip);
      bar.appendChild(allChip);

      for (let start = minNum; start <= maxNum; start += rangeSize) {
        const end = Math.min(start + rangeSize - 1, maxNum);
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'episode-range-chip';
        chip.textContent = `${start} - ${end}`;
        chip.onclick = () => filterEpisodeRange(`${start}-${end}`, chip);
        bar.appendChild(chip);
      }
    }
  }

  const searchInput = document.getElementById('episode-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const q = e.target.value.trim();
      if (!q) {
        filterEpisodeRange(currentRange);
        return;
      }
      items.forEach(el => {
        const n = el.dataset.num;
        el.style.display = (n === q || (el.dataset.title || '').toLowerCase().includes(q.toLowerCase())) ? '' : 'none';
      });
    });
  }
}

function filterEpisodeRange(range, chipEl = null) {
  currentRange = range;
  if (chipEl) {
    document.querySelectorAll('.episode-range-chip').forEach(c => c.classList.remove('active'));
    chipEl.classList.add('active');
  }
  const items = document.querySelectorAll('.episode-item');
  if (range === 'all') {
    items.forEach(el => el.style.display = '');
    return;
  }
  const [start, end] = range.split('-').map(Number);
  items.forEach(el => {
    const n = parseInt(el.dataset.num, 10);
    el.style.display = (n >= start && n <= end) ? '' : 'none';
  });
}

function selectBatchFilter(mode) {
  const items = document.querySelectorAll('.episode-item');
  items.forEach(row => {
    if (row.style.display === 'none') return;
    const cb = row.querySelector('.episode-check');
    if (!cb) return;

    if (mode === 'not-downloaded') {
      cb.checked = !row.classList.contains('ep-downloaded');
    } else if (mode === 'not-watched') {
      cb.checked = !row.classList.contains('ep-watched');
    } else if (mode === 'invert') {
      cb.checked = !cb.checked;
    }
  });
  onEpisodeCheckChange();
}

// =========================================================================
// Calcul de l'ETA et vitesse de téléchargement
// =========================================================================

function formatEta(seconds) {
  if (isNaN(seconds) || seconds <= 0 || !isFinite(seconds)) return '';
  if (seconds < 60) return `~${seconds}s restantes`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) return `~${mins}m ${secs}s`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `~${hours}h ${remMins}m`;
}

function parseSpeedToBytes(speedStr) {
  if (!speedStr || typeof speedStr !== 'string') return 0;
  const match = speedStr.match(/^([\d.]+)\s*([KMGT]?B\/s)/i);
  if (!match) return 0;
  const val = parseFloat(match[1]);
  const unit = match[2].toUpperCase();
  if (unit.startsWith('K')) return val * 1024;
  if (unit.startsWith('M')) return val * 1024 * 1024;
  if (unit.startsWith('G')) return val * 1024 * 1024 * 1024;
  return val;
}

// =========================================================================
// Fonctions de vérification d'intégrité et de re-téléchargement
// =========================================================================

async function verifyTask(taskId, triggerEl) {
  const btn = triggerEl || document.querySelector(`[data-id="${taskId}"] [onclick*="verifyTask"]`);
  const originalHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm" style="display:inline-block;width:12px;height:12px;"></span>';
  }
  showToast('Vérification du fichier en cours...', 'info');

  try {
    const resp = await fetch(`/api/download/${taskId}/verify`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      showToast(data.error || 'Erreur lors de la vérification', 'error');
      return;
    }

    if (data.valid) {
      const dur = data.formattedDuration ? ` (${data.formattedDuration})` : '';
      showToast(`Fichier intègre et lisible${dur} • ${data.formattedSize}`, 'success');
    } else {
      showToast(`Problème détecté : ${data.error || data.status}`, 'error');
    }

    // Mettre à jour l'élément dans downloads ou history
    const row = document.getElementById(`task-${taskId}`) || document.getElementById(`history-row-${taskId}`);
    if (row) {
      row.dataset.verification = data.status;
      const verifBadge = row.querySelector('.dl-verif-badge') || document.getElementById(`history-verif-badge-${taskId}`);
      if (verifBadge) {
        if (data.valid) {
          verifBadge.className = 'status-badge dl-verif-badge badge-ok';
          verifBadge.textContent = `✓ Valide${data.formattedDuration ? ' • ' + data.formattedDuration : ''}`;
          verifBadge.title = 'Fichier intègre et lisible sur le disque';
        } else if (data.status === 'MISSING') {
          verifBadge.className = 'status-badge dl-verif-badge badge-err';
          verifBadge.textContent = '⚠ Manquant';
          verifBadge.title = data.error || 'Fichier introuvable sur le disque';
        } else if (data.status === 'EMPTY') {
          verifBadge.className = 'status-badge dl-verif-badge badge-err';
          verifBadge.textContent = '✗ Vide';
          verifBadge.title = 'Fichier de 0 octet';
        } else {
          verifBadge.className = 'status-badge dl-verif-badge badge-err';
          verifBadge.textContent = '✗ Corrompu';
          verifBadge.title = data.error || 'Fichier vidéo corrompu';
        }
      }

      const actEl = row.querySelector('.dl-task-actions');
      if (actEl) {
        const taskObj = {
          id: taskId,
          status: row.dataset.status || 'COMPLETED',
          verificationStatus: data.status,
          animeName: actEl.dataset.animename || '',
          episodeNumber: actEl.dataset.episodenumber || '',
        };
        actEl.innerHTML = renderTaskActions(taskObj);
      }
    }
  } catch (e) {
    showToast('Erreur de communication : ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

async function verifyAllCompletedTasks() {
  const btn = document.getElementById('btn-verify-all-downloads') || document.getElementById('btn-verify-history');
  const originalHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm" style="display:inline-block;width:14px;height:14px;margin-right:6px;"></span>Vérification en cours...';
  }
  showToast('Vérification de l\'ensemble des fichiers en cours...', 'info');

  try {
    const resp = await fetch('/api/download/verify-all', { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      showToast(data.error || 'Erreur lors de la vérification globale', 'error');
      return;
    }

    const issues = (data.missing || 0) + (data.corrupted || 0) + (data.empty || 0);
    if (issues === 0) {
      showToast(`Tous les fichiers (${data.valid}/${data.total}) sont intègres et valides !`, 'success');
    } else {
      showToast(`Vérification : ${data.valid} valide(s), ${data.missing} manquant(s), ${data.corrupted + data.empty} corrompu(s)`, 'error');
    }

    if (Array.isArray(data.results)) {
      data.results.forEach(res => {
        const row = document.getElementById(`task-${res.taskId}`) || document.getElementById(`history-row-${res.taskId}`);
        if (row) {
          row.dataset.verification = res.status;
          const badge = row.querySelector('.dl-verif-badge') || document.getElementById(`history-verif-badge-${res.taskId}`);
          if (badge) {
            if (res.valid) {
              badge.className = 'status-badge dl-verif-badge badge-ok';
              badge.textContent = `✓ Valide${res.formattedDuration ? ' • ' + res.formattedDuration : ''}`;
              badge.title = 'Fichier intègre et lisible sur le disque';
            } else if (res.status === 'MISSING') {
              badge.className = 'status-badge dl-verif-badge badge-err';
              badge.textContent = '⚠ Manquant';
              badge.title = res.error || 'Fichier introuvable';
            } else if (res.status === 'EMPTY') {
              badge.className = 'status-badge dl-verif-badge badge-err';
              badge.textContent = '✗ Vide';
              badge.title = 'Fichier de 0 octet';
            } else {
              badge.className = 'status-badge dl-verif-badge badge-err';
              badge.textContent = '✗ Corrompu';
              badge.title = res.error || 'Fichier corrompu';
            }
          }

          const actEl = row.querySelector('.dl-task-actions');
          if (actEl) {
            const taskObj = {
              id: res.taskId,
              status: row.dataset.status || 'COMPLETED',
              verificationStatus: res.status,
              animeName: actEl.dataset.animename || '',
              episodeNumber: actEl.dataset.episodenumber || '',
            };
            actEl.innerHTML = renderTaskActions(taskObj);
          }
        }
      });
    }
  } catch (e) {
    showToast('Erreur : ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

async function redownloadTask(taskId) {
  showToast('Relance du téléchargement...', 'info');
  try {
    const resp = await fetch(`/api/download/${taskId}/redownload`, { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message || 'Téléchargement relancé avec succès', 'success');
      const activeTabBtn = document.querySelector('.dl-tab[data-group="active"]');
      if (activeTabBtn) {
        activeTabBtn.click();
      } else if (window.location.pathname === '/history') {
        setTimeout(() => { window.location.href = '/downloads'; }, 800);
      }
    } else {
      showToast(data.error || 'Impossible de relancer le téléchargement', 'error');
    }
  } catch (e) {
    showToast('Erreur : ' + e.message, 'error');
  }
}

