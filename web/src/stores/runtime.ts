import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import type { Health, PluginSummary, PublicEvent, TaskSummary } from '@/api/client'
import { getJson } from '@/api/client'

export const useRuntimeStore = defineStore('runtime', () => {
  const health = ref<Health | null>(null)
  const plugins = ref<PluginSummary[]>([])
  const tasks = ref<TaskSummary[]>([])
  const events = ref<PublicEvent[]>([])
  const error = ref<string | null>(null)
  const loading = ref(false)
  const connected = ref(false)
  let eventSource: EventSource | null = null

  const availableTasks = computed(() => tasks.value.filter((task) => task.available).length)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [nextHealth, nextPlugins, nextTasks] = await Promise.all([
        getJson<Health>('/api/v1/health'),
        getJson<PluginSummary[]>('/api/v1/plugins'),
        getJson<TaskSummary[]>('/api/v1/tasks'),
      ])
      health.value = nextHealth
      plugins.value = nextPlugins
      tasks.value = nextTasks
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  function connectEvents(): void {
    eventSource?.close()
    eventSource = new EventSource('/api/v1/events/stream')
    eventSource.onopen = () => {
      connected.value = true
    }
    eventSource.onerror = () => {
      connected.value = false
    }
    eventSource.onmessage = (message) => {
      const event = JSON.parse(message.data) as PublicEvent
      events.value = [...events.value.slice(-199), event]
    }
  }

  return {
    availableTasks,
    connected,
    error,
    events,
    health,
    loading,
    plugins,
    tasks,
    connectEvents,
    refresh,
  }
})
