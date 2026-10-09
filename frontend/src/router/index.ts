import { createRouter, createWebHistory } from 'vue-router';
import { getRouterBase } from './base';
import { useSearchContext } from '@/stores/searchContext';

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

const positions = new Map<string, {left: number; top: number}>();
const router = createRouter({
  history: createWebHistory(getRouterBase(window.location.pathname)),
  routes,
  scrollBehavior(to, _from, savedPosition) {
    return savedPosition || positions.get(to.fullPath) || { top: 0 };
  },
});

router.beforeEach((_to, from) => {
  positions.set(from.fullPath, {left: window.scrollX, top: window.scrollY});
  if (positions.size > 50) positions.delete(positions.keys().next().value!);
});

router.afterEach((to, from, failure) => {
  if (!failure && from.name === 'anime-detail' && to.name !== 'anime-detail') {
    useSearchContext().detailUrl = '';
  }
});

export default router;
