<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAvatarSession } from './composables/useAvatarSession'

const session = useAvatarSession()
const textInput = ref('')

const sendText = () => {
  session.sendText(textInput.value)
  textInput.value = ''
}

const toggleConnect = () => {
  if (session.status.value === 'connected') session.disconnect()
  else session.connect()
}

onMounted(() => session.checkHealth())

const entryClass = (role: string) => `entry entry-${role}`
</script>

<template>
  <div class="page">
    <header class="header">
      <h1>🎙️ online-avatar 数字人对话</h1>
      <div class="controls">
        <label>
          方案
          <select v-model="session.solution.value" :disabled="session.status.value === 'connected'">
            <option value="cascade">cascade（ASR→LLM→TTS 级联）</option>
            <option value="echo">echo（mock，无需密钥）</option>
          </select>
        </label>
        <button :class="{ danger: session.status.value === 'connected' }" @click="toggleConnect">
          {{ session.status.value === 'connected' ? '断开' : '连接' }}
        </button>
        <span class="status" :class="session.status.value">
          {{ session.status.value === 'connected' ? '🟢 已连接' : '⚪ 未连接' }}
        </span>
        <span v-if="session.serverConfigured.value === false" class="warn">
          服务端未配置 DASHSCOPE_API_KEY，cascade 不可用
        </span>
      </div>
    </header>

    <main class="main">
      <div class="avatar" :class="{ speaking: session.turnActive.value }">
        <div class="face">{{ session.turnActive.value ? '🗣️' : '🙂' }}</div>
        <div class="avatar-status">
          <template v-if="session.turnActive.value">正在回答…</template>
          <template v-else-if="session.listening.value">聆听中，请说话</template>
          <template v-else>待机</template>
        </div>
        <div v-if="session.asrDraft.value" class="asr-draft">识别中：{{ session.asrDraft.value }}</div>
      </div>

      <div class="chat">
        <div v-for="e in session.entries.value" :key="e.id" :class="entryClass(e.role)">
          <span class="role">{{ { user: '你', bot: '数字人', system: '系统', error: '错误' }[e.role] }}</span>
          <span class="text">{{ e.text }}</span>
        </div>
      </div>
    </main>

    <footer class="footer">
      <button :disabled="session.status.value !== 'connected'" @click="session.toggleMic()">
        {{ session.listening.value ? '🛑 停止说话' : '🎤 开始说话' }}
      </button>
      <button
        class="danger"
        :disabled="session.status.value !== 'connected'"
        @click="session.interrupt()"
      >
        ⏹ 打断
      </button>
      <input
        v-model="textInput"
        type="text"
        placeholder="或输入文字直接对话（跳过 ASR）"
        @keydown.enter="sendText"
      />
      <button :disabled="session.status.value !== 'connected'" @click="sendText">发送</button>
    </footer>
  </div>
</template>

<style scoped>
.page { max-width: 820px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }
.header h1 { font-size: 20px; margin: 0 0 8px; }
.controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 14px; }
.status.connected { color: #2a9d5c; }
.warn { color: #c07f00; font-size: 13px; }
.main { flex: 1; display: flex; gap: 16px; margin: 16px 0; min-height: 0; }
.avatar { width: 220px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.face { font-size: 64px; transition: transform .2s; }
.avatar.speaking .face { animation: bounce .6s infinite alternate; }
@keyframes bounce { from { transform: scale(1); } to { transform: scale(1.12); } }
.avatar-status { font-size: 13px; color: #666; }
.asr-draft { font-size: 12px; color: #4a7dff; max-width: 200px; }
.chat { flex: 1; overflow-y: auto; background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 12px; }
.entry { display: flex; gap: 8px; margin-bottom: 10px; font-size: 14px; line-height: 1.6; }
.role { flex-shrink: 0; font-weight: 600; }
.entry-user .role { color: #2a9d5c; }
.entry-bot .role { color: #4a7dff; }
.entry-system { color: #999; font-size: 12px; }
.entry-error { color: #d05555; font-size: 12px; }
.footer { display: flex; gap: 8px; }
.footer input { flex: 1; }
</style>
