<script setup>
import WelcomeCard from './WelcomeCard.vue'
import MessageItem from './MessageItem.vue'
import ChatInput from './ChatInput.vue'
import VideoDock from './VideoDock.vue'
import ResumeDock from './ResumeDock.vue'

defineProps({
  messages: Array,
  isLoading: Boolean,
  videoClip: Object,
  resumeArtifact: Object,
})

const emit = defineEmits([
  'send',
  'selectOption',
  'playCitation',
  'closeVideo',
  'openResume',
  'closeResume',
  'enterInterview',
])
</script>

<template>
  <div class="chat-view">
    <!-- Messages area -->
    <div class="messages-container" ref="messagesContainer">
      <WelcomeCard
        v-if="messages.length === 0"
        @send="emit('send', $event)"
        @enterInterview="emit('enterInterview', $event || {})"
      />
      <div v-else class="message-list">
        <MessageItem
          v-for="(msg, index) in messages"
          :key="index"
          :message="msg"
          @selectOption="emit('selectOption', $event)"
          @playCitation="emit('playCitation', $event)"
          @openResume="emit('openResume', $event)"
          @enterInterview="emit('enterInterview', $event || {})"
        />
        <!-- Loading indicator：仅在尚无流式气泡时显示 -->
        <div v-if="isLoading && !messages.some(m => m.streaming)" class="loading-indicator">
          <div class="typing-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <VideoDock v-if="videoClip" :clip="videoClip" @close="emit('closeVideo')" />
    <ResumeDock
      v-else-if="resumeArtifact"
      :artifact="resumeArtifact"
      @close="emit('closeResume')"
    />

    <!-- Input area -->
    <ChatInput
      :disabled="isLoading"
      @send="emit('send', $event)"
    />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
}

.messages-container {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 0 16px;
}

.message-list {
  max-width: 768px;
  margin: 0 auto;
  padding: 24px 0;
}

.loading-indicator {
  display: flex;
  justify-content: flex-start;
  padding: 16px 0;
  max-width: 768px;
  margin: 0 auto;
}

.typing-dots {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border-radius: 12px;
  border-top-left-radius: 4px;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: typing 1.4s infinite ease-in-out both;
}

.typing-dots span:nth-child(1) { animation-delay: -0.32s; }
.typing-dots span:nth-child(2) { animation-delay: -0.16s; }
.typing-dots span:nth-child(3) { animation-delay: 0s; }

@keyframes typing {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.4;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
