import { createRouter, createWebHistory } from 'vue-router';
import { getRouterBase } from './base';

const routes = [
  {
    path: '/sources/:sourceId?',
    name: 'sources',
    component: () => import('@/views/SourcesView.vue'),
  },
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
  },
  {
    path: '/anime',
    name: 'anime-detail',
    component: () => import('@/views/AnimeDetailView.vue'),
  },
  {
    path: '/downloads',
    name: 'downloads',
    component: () => import('@/views/DownloadsView.vue'),
  },
  {
    path: '/library',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
  },
  {
    path: '/favorites',
    redirect: '/library',
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
  },
  {
    path: '/extensions',
    name: 'extensions',
    component: () => import('@/views/ExtensionsView.vue'),
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
];

const router = createRouter({
  history: createWebHistory(getRouterBase(window.location.pathname)),
  routes,
  scrollBehavior() {
    return { top: 0 };
  },
});

export default router;
