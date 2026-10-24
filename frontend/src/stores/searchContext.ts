import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSearchContext = defineStore('search-context', () => {
  const detailUrl = ref('')
  const restoreSequence = ref(0)
  function markDetail(url: string) {
    detailUrl.value = url
  }
  function restore(url: string) {
    if (url !== detailUrl.value || !url) return false
    restoreSequence.value++
    return true
  }
  return { detailUrl, restoreSequence, markDetail, restore }
})
