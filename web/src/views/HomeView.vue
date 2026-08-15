<script setup lang="ts">
import { onMounted } from 'vue'

import { useRuntimeStore } from '@/stores/runtime'

const runtime = useRuntimeStore()

onMounted(() => {
  void runtime.refresh()
  runtime.connectEvents()
})
</script>

<template>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">ANDROID VISUAL AUTOMATION</p>
        <h1>TheBridge</h1>
        <p class="subtitle">插件、任务状态图与视觉能力之间的窄桥。</p>
      </div>
      <span class="status" :class="{ online: runtime.connected }">
        {{ runtime.connected ? '事件流已连接' : '等待后端' }}
      </span>
    </header>

    <p v-if="runtime.error" class="error">{{ runtime.error }}</p>

    <section class="summary">
      <article>
        <span>后端</span>
        <strong>{{ runtime.health?.version ?? '—' }}</strong>
      </article>
      <article>
        <span>已激活插件</span>
        <strong>{{ runtime.plugins.filter((plugin) => plugin.active).length }}</strong>
      </article>
      <article>
        <span>可运行任务</span>
        <strong>{{ runtime.availableTasks }}</strong>
      </article>
    </section>

    <section class="grid">
      <article class="panel">
        <div class="panel-title">
          <h2>插件</h2>
          <button type="button" :disabled="runtime.loading" @click="runtime.refresh">
            刷新
          </button>
        </div>
        <ul>
          <li v-for="plugin in runtime.plugins" :key="plugin.id">
            <div>
              <strong>{{ plugin.id }}</strong>
              <small>v{{ plugin.version }}</small>
            </div>
            <span :class="plugin.active ? 'good' : 'muted'">
              {{ plugin.active ? 'active' : 'inactive' }}
            </span>
          </li>
        </ul>
      </article>

      <article class="panel">
        <div class="panel-title"><h2>任务</h2></div>
        <ul>
          <li v-for="task in runtime.tasks" :key="task.id">
            <div>
              <strong>{{ task.title }}</strong>
              <small>{{ task.id }} · {{ task.stage }}</small>
              <small v-if="task.missing_services.length">
                缺少：{{ task.missing_services.join(', ') }}
              </small>
              <small v-if="task.missing_artifacts.length">
                缺少资源：{{ task.missing_artifacts.join(', ') }}
              </small>
            </div>
            <span :class="task.available ? 'good' : 'muted'">
              {{ task.available ? 'ready' : 'unavailable' }}
            </span>
          </li>
        </ul>
      </article>
    </section>

    <section class="panel events">
      <div class="panel-title"><h2>运行事件</h2></div>
      <p v-if="runtime.events.length === 0" class="empty">暂无事件。</p>
      <ol v-else>
        <li v-for="event in runtime.events" :key="event.id">
          <time>{{ new Date(event.ts).toLocaleTimeString() }}</time>
          <code>{{ event.kind }}</code>
          <span>{{ event.source }}</span>
        </li>
      </ol>
    </section>
  </main>
</template>
