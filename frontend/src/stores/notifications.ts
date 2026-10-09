import { defineStore } from 'pinia';
import { ref } from 'vue';

type Tone = 'success' | 'error' | 'info';
export interface Notification {
  id: number;
  message: string;
  tone: Tone;
  action?: { label: string; run: () => unknown | Promise<unknown> };
  busy?: boolean;
}

export const useNotifications = defineStore('notifications', () => {
  const items = ref<Notification[]>([]);
  const timers = new Map<number, ReturnType<typeof setTimeout>>();
  let sequence = 0;
  function dismiss(id: number) {
    clearTimeout(timers.get(id)); timers.delete(id);
    items.value = items.value.filter(item => item.id !== id);
  }
  function pause(id: number) { clearTimeout(timers.get(id)); timers.delete(id); }
  function resume(id: number) {
    pause(id);
    const item = items.value.find(item => item.id === id);
    if (item && !item.busy) timers.set(id, setTimeout(() => dismiss(id), item.action ? 15000 : 6000));
  }
  function notify(message: string, tone: Tone = 'success', action?: Notification['action']) {
    const id = ++sequence;
    items.value.push({ id, message, tone, action });
    resume(id);
    return id;
  }
  async function act(id: number) {
    const item = items.value.find(item => item.id === id);
    if (!item?.action || item.busy) return;
    pause(id); item.busy = true;
    try { await item.action.run(); dismiss(id); }
    catch (error) {
      item.busy = false;
      notify(error instanceof Error ? error.message : 'Impossible de terminer cette action.', 'error');
      resume(id);
    }
  }
  return { items, notify, dismiss, pause, resume, act };
});
