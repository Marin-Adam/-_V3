<template>
  <div class="agent-page">
    <div class="chat-main">
      <div class="messages-container" ref="msgContainer">
        <div v-if="messages.length === 0" class="welcome">
          <h2>🤖 AI 电商智能分析师</h2>
          <p>实时销售分析 · 异常检测 · 竞品监控 · 库存优化</p>
          <div class="quick-asks">
            <el-tag v-for="q in quickQuestions" :key="q" class="q-tag" @click="send(q)">{{ q }}</el-tag>
          </div>
        </div>
        <div v-for="(msg, i) in messages" :key="i" class="msg" :class="msg.role">
          <div class="msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="msg-body">
            <div class="msg-text" v-html="md(msg.text)"></div>

            <!-- Memory references -->
            <div v-if="msg.memoryRefs?.length" class="msg-memory">
              <el-collapse>
                <el-collapse-item :title="'🧠 参考了 ' + msg.memoryRefs.length + ' 条历史分析'">
                  <div v-for="(ref, ri) in msg.memoryRefs" :key="ri" class="memory-item">
                    {{ ref.content?.substring(0, 200) }}...
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>

            <!-- Tool call steps -->
            <div v-if="msg.steps?.length" class="msg-steps">
              <el-collapse>
                <el-collapse-item :title="'🔧 分析过程 (' + msg.steps.length + ' 步, ' + (msg.latency_ms || 0).toFixed(0) + 'ms)'">
                  <div v-for="(step, si) in msg.steps" :key="si" class="step-item">
                    <div class="step-thought">
                      <el-tag size="small" type="warning">Step {{ step.step_num }}</el-tag>
                      {{ step.thought }}
                    </div>
                    <div v-if="step.action" class="step-action">
                      → 调用 <code>{{ step.action }}</code>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>

            <!-- Skills used -->
            <div v-if="msg.skills?.length" class="msg-meta">
              <el-tag size="small" type="success" v-for="s in msg.skills" :key="s">🧩 {{ s }}</el-tag>
            </div>

            <!-- Tools called -->
            <div v-if="msg.tools?.length" class="msg-meta">
              <el-tag size="small" type="info" v-for="t in msg.tools" :key="t">🔧 {{ t }}</el-tag>
            </div>
          </div>
        </div>
        <div v-if="loading" class="msg assistant">
          <div class="msg-avatar">🤖</div>
          <div class="msg-body"><div class="msg-text streaming">分析中...</div></div>
        </div>
      </div>
      <div class="input-area">
        <el-input v-model="input" type="textarea" :rows="2"
          placeholder="输入分析问题，如：分析今天的销售异常..."
          @keydown.enter.exact.prevent="send()" :disabled="loading" />
        <el-button type="primary" @click="send()" :loading="loading" style="margin-top:8px">
          {{ loading ? '分析中' : '发送' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { marked } from 'marked'
import { agentAPI } from '@/services/api'

const messages = ref([])
const input = ref('')
const loading = ref(false)
const msgContainer = ref(null)

const quickQuestions = [
  '分析今天的销售异常',
  '哪些商品需要补货？',
  '竞品价格有什么变化？',
  '今天的GMV趋势如何？',
]

function md(text) { return text ? marked.parse(text) : '' }

async function send(preset) {
  const text = preset || input.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', text })
  input.value = ''
  loading.value = true
  try {
    const { data } = await agentAPI.chat(text)
    messages.value.push({
      role: 'assistant',
      text: data.answer,
      skills: data.skills_used,
      tools: data.tools_called,
      steps: data.steps,
      memory_refs: data.memory_refs,
      latency_ms: data.latency_ms,
    })
  } catch (e) {
    messages.value.push({ role: 'assistant', text: '分析请求失败，请稍后重试。' })
  } finally {
    loading.value = false
    await nextTick()
    if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  }
}
</script>

<style scoped>
.agent-page { max-width: 960px; margin: 0 auto; height: calc(100vh - 120px); display: flex; flex-direction: column; }
.chat-main { flex: 1; display: flex; flex-direction: column; }
.messages-container { flex: 1; overflow-y: auto; padding: 20px; }
.welcome { text-align: center; padding: 60px 20px; }
.welcome h2 { color: #4fc3f7; font-size: 24px; margin-bottom: 12px; }
.welcome p { color: #a0a0b0; margin-bottom: 20px; }
.q-tag { margin: 4px; cursor: pointer; background: #2a2a3e; border-color: #3a3a5e; color: #a0a0b0; }
.q-tag:hover { background: #3a3a5e; color: #4fc3f7; }
.msg { display: flex; gap: 12px; margin-bottom: 20px; }
.msg.user { flex-direction: row-reverse; }
.msg-avatar { width: 36px; height: 36px; border-radius: 50%; background: #2a2a3e; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.msg-body { max-width: 82%; }
.msg-text { background: #1a1a2e; border-radius: 12px; padding: 12px 16px; line-height: 1.6; color: #e0e0e0; word-wrap: break-word; }
.msg.user .msg-text { background: #1a3a5e; }
.msg-text :deep(p) { margin-bottom: 8px; }
.msg-text :deep(strong) { color: #4fc3f7; }
.msg-text :deep(table) { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.msg-text :deep(th), .msg-text :deep(td) { border: 1px solid #2a2a3e; padding: 6px 12px; text-align: left; }
.msg-text :deep(th) { background: #2a2a3e; }
.msg-text :deep(blockquote) { border-left: 3px solid #4fc3f7; padding-left: 12px; margin: 8px 0; color: #aaaaaa; }

/* Memory collapse */
.msg-memory { margin-top: 8px; }
.msg-memory :deep(.el-collapse) { border: none; background: transparent; }
.msg-memory :deep(.el-collapse-item__header) { color: #ffa726; background: #1a1a2e; border: 1px solid #2a2a3e; border-radius: 8px; padding: 6px 12px; font-size: 13px; }
.msg-memory :deep(.el-collapse-item__wrap) { background: #1a1a2e; border: 1px solid #2a2a3e; border-top: none; border-radius: 0 0 8px 8px; }
.memory-item { padding: 8px 12px; color: #a0a0b0; font-size: 12px; border-bottom: 1px solid #2a2a3e; }
.memory-item:last-child { border-bottom: none; }

/* Steps collapse */
.msg-steps { margin-top: 8px; }
.msg-steps :deep(.el-collapse) { border: none; background: transparent; }
.msg-steps :deep(.el-collapse-item__header) { color: #66bb6a; background: #1a1a2e; border: 1px solid #2a2a3e; border-radius: 8px; padding: 6px 12px; font-size: 13px; }
.msg-steps :deep(.el-collapse-item__wrap) { background: #1a1a2e; border: 1px solid #2a2a3e; border-top: none; border-radius: 0 0 8px 8px; }
.step-item { padding: 8px 12px; border-bottom: 1px solid #2a2a3e; }
.step-item:last-child { border-bottom: none; }
.step-thought { color: #e0e0e0; font-size: 13px; margin-bottom: 4px; }
.step-action { color: #888; font-size: 12px; padding-left: 32px; }
.step-action code { background: #0a0a1a; padding: 2px 6px; border-radius: 4px; color: #4fc3f7; }

.msg-meta { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
.streaming { border-left: 3px solid #4fc3f7; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
.input-area { padding: 16px 20px; background: #1a1a2e; border-top: 1px solid #2a2a3e; }
</style>
