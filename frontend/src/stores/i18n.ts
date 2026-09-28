import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';

export const useI18nStore = defineStore('i18n', () => {
  const currentLang = ref<'fr' | 'en'>('fr');
  const translations = ref<Record<string, string>>({});
  const isLoaded = ref(false);

  // Helper to read cookie
  function getCookie(name: string): string | null {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? decodeURIComponent(match[2]) : null;
  }

  async function init() {
    const cookieLang = getCookie('animan_lang');
    const localLang = localStorage.getItem('animan_lang');
    const lang = (cookieLang || localLang || 'fr') as 'fr' | 'en';
    currentLang.value = lang === 'en' ? 'en' : 'fr';
    localStorage.setItem('animan_lang', currentLang.value);

    try {
      const res = await api.getTranslations(currentLang.value);
      if (res && res.translations) {
        translations.value = res.translations;
      }
    } catch (e) {
      console.warn('[i18n] Failed to load translations:', e);
    } finally {
      isLoaded.value = true;
    }
  }

  async function changeLanguage(lang: 'fr' | 'en') {
    currentLang.value = lang;
    localStorage.setItem('animan_lang', lang);
    document.cookie = `animan_lang=${lang};path=/;max-age=31536000;SameSite=Lax`;

    try {
      await api.setLanguage(lang);
      const res = await api.getTranslations(lang);
      if (res && res.translations) {
        translations.value = res.translations;
      }
    } catch (e) {
      console.warn('[i18n] Failed to update server language:', e);
    }
  }

  function t(key: string, params?: Record<string, string | number>): string {
    let str = translations.value[key] || key;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
      }
    }
    return str;
  }

  return {
    currentLang,
    translations,
    isLoaded,
    init,
    changeLanguage,
    t,
  };
});
