/**
 * 聊天语音 composable — 轻量级语音输入 + TTS 播放。
 * 直接复用 /api/interview/asr 和 /api/interview/tts 后端。
 *
 * 用法（Vue setup）：
 *   // 录音（ChatInput 使用，每个组件独立实例）
 *   const { isRecording, audioLevel, startRecording, stopRecording }
 *     = useVoiceChat()
 *
 *   // TTS 播放（MessageItem 使用，全局单例共享 isSpeaking）
 *   const { isSpeaking, speak, stopSpeaking }
 *     = useVoiceChat()   // isSpeaking 全局共享，speak/stopSpeaking 也是单例
 */

import { ref } from 'vue'

const API_ORIGIN = 'http://127.0.0.1:8000'
const API_BASE = `${API_ORIGIN}/api`

// ── VAD 参数（与 useInterviewSession.js 一致）──────────
const SPEAK_ON = 0.045
const SPEAK_OFF = 0.028
const SILENCE_MS = 700
const MIN_CAPTURE_MS = 400
const MAX_CAPTURE_MS = 20000
const MIN_UTTER_SEC = 0.3

// ══════════════════════════════════════════════════════
// TTS 播放 — 模块级单例，所有 MessageItem 共享
// ══════════════════════════════════════════════════════

const isSpeaking = ref(false)
let speakingAudio = null
let speakingUrl = null

/** 全局单例：TTS 播报。LLM 已在生成时输出口语，直接送 TTS。 */
/** 全局单例：TTS 播报。LLM 已在生成时输出口语，直接送 TTS。 */
async function speak(text) {
  console.log('[TTS] speak called with', (text || '').length, 'chars')
  stopSpeaking()
  if (!(text || '').trim()) { console.log('[TTS] empty text'); return }

  isSpeaking.value = true

  const resp = await fetch(`${API_BASE}/interview/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text.trim() }),
  })
  if (!resp.ok) {
    isSpeaking.value = false
    let detail = ''
    try { detail = (await resp.json()).detail || '' } catch { detail = await resp.text() }
    throw new Error(`TTS HTTP ${resp.status}${detail ? `: ${String(detail).slice(0, 160)}` : ''}`)
  }
  const buf = await resp.arrayBuffer()

  stopSpeaking()
  const mime = resp.headers.get('content-type') || 'audio/mpeg'
  speakingUrl = URL.createObjectURL(new Blob([buf], { type: mime.split(';')[0].trim() }))
  speakingAudio = new Audio(speakingUrl)
  isSpeaking.value = true

  await new Promise((resolve, reject) => {
    const done = () => {
      speakingAudio = null
      isSpeaking.value = false
      resolve()
    }
    speakingAudio.onended = done
    speakingAudio.onerror = () => {
      speakingAudio = null
      isSpeaking.value = false
      reject(new Error('TTS 播放失败'))
    }
    speakingAudio._vcResolve = done
    speakingAudio.play().then(() => {
      console.log('[TTS] playing')
    }).catch(reject)
  })
}

function stopSpeaking() {
  if (speakingAudio) {
    const resolve = speakingAudio._vcResolve
    try {
      speakingAudio.pause()
      speakingAudio.onended = null
      speakingAudio.onerror = null
    } catch { /* ignore */ }
    speakingAudio = null
    resolve?.()
  }
  if (speakingUrl) {
    URL.revokeObjectURL(speakingUrl)
    speakingUrl = null
  }
  isSpeaking.value = false
}

// ══════════════════════════════════════════════════════
// 语音输入 — 每次调用创建独立实例（录音与 ChatInput 绑定）
// ══════════════════════════════════════════════════════

/**
 * @param {{ onError?: (msg: string) => void }} [opts]
 */
export function useVoiceChat(opts = {}) {
  // ── 录音状态（每个组件独立）──
  const isRecording = ref(false)
  const audioLevel = ref(0)

  // ── 内部变量 ──
  let stream = null
  let audioCtx = null
  let analyser = null
  let micSource = null
  let rafId = 0
  /** @type {ScriptProcessorNode | null} */
  let captureNode = null
  let silentGain = null
  /** @type {Float32Array[]} */
  let pcmChunks = []
  let captureSampleRate = 16000
  let captureStartedAt = 0
  let lastLoudAt = 0
  let noiseFloor = 0.02
  let speechPeak = 0
  let generation = 0
  /** 录音停止时 resolve(text) */
  let recordingResolve = null

  // ── WAV 编码 ──

  function writeStr(view, offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i))
    }
  }

  function writeWavHeader(view, dataBytes, sampleRate, channels) {
    const blockAlign = channels * 2
    const byteRate = sampleRate * blockAlign
    writeStr(view, 0, 'RIFF')
    view.setUint32(4, 36 + dataBytes, true)
    writeStr(view, 8, 'WAVE')
    writeStr(view, 12, 'fmt ')
    view.setUint32(16, 16, true)
    view.setUint16(20, 1, true)
    view.setUint16(22, channels, true)
    view.setUint32(24, sampleRate, true)
    view.setUint32(28, byteRate, true)
    view.setUint16(32, blockAlign, true)
    view.setUint16(34, 16, true)
    writeStr(view, 36, 'data')
    view.setUint32(40, dataBytes, true)
  }

  function encodeWav(chunks, sampleRate) {
    let total = 0
    for (const c of chunks) total += c.length
    const buffer = new ArrayBuffer(44 + total * 2)
    const view = new DataView(buffer)
    writeWavHeader(view, total * 2, sampleRate, 1)
    let offset = 44
    for (const c of chunks) {
      for (let i = 0; i < c.length; i++) {
        const s = Math.max(-1, Math.min(1, c[i]))
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
        offset += 2
      }
    }
    return new Blob([buffer], { type: 'audio/wav' })
  }

  // ── 媒体管线 ──

  async function ensureMic() {
    if (stream && audioCtx && analyser) return
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
        channelCount: 1,
      },
    })
    audioCtx = new AudioContext()
    if (audioCtx.state === 'suspended') {
      await audioCtx.resume()
    }
    captureSampleRate = audioCtx.sampleRate || 48000
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 2048
    micSource = audioCtx.createMediaStreamSource(stream)
    micSource.connect(analyser)
  }

  async function cleanupMedia() {
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = 0
    }
    teardownCaptureNode()
    try { micSource?.disconnect() } catch { /* ignore */ }
    micSource = null
    analyser = null
    if (audioCtx) {
      try { await audioCtx.close() } catch { /* ignore */ }
      audioCtx = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
  }

  // ── 录音 Capture ──

  function teardownCaptureNode() {
    if (captureNode) {
      try { captureNode.disconnect() } catch { /* ignore */ }
      captureNode.onaudioprocess = null
      captureNode = null
    }
    if (silentGain) {
      try { silentGain.disconnect() } catch { /* ignore */ }
      silentGain = null
    }
  }

  function beginCapture(gen) {
    if (gen !== generation || !stream || !audioCtx || !micSource || captureNode) return
    pcmChunks = []
    speechPeak = 0
    captureStartedAt = performance.now()
    lastLoudAt = captureStartedAt
    captureSampleRate = audioCtx.sampleRate || captureSampleRate

    try {
      captureNode = audioCtx.createScriptProcessor(4096, 1, 1)
      silentGain = audioCtx.createGain()
      silentGain.gain.value = 0
      captureNode.onaudioprocess = (ev) => {
        if (!isRecording.value) return
        const input = ev.inputBuffer.getChannelData(0)
        pcmChunks.push(new Float32Array(input))
      }
      micSource.connect(captureNode)
      captureNode.connect(silentGain)
      silentGain.connect(audioCtx.destination)
    } catch (e) {
      opts.onError?.(`无法录音: ${e.message}`)
      teardownCaptureNode()
    }
  }

  function stopCapture(keepChunks) {
    teardownCaptureNode()
    if (!keepChunks) pcmChunks = []
  }

  async function finishCapture(gen) {
    if (gen !== generation || !captureNode) return
    const chunks = pcmChunks
    const rate = captureSampleRate
    stopCapture(true)
    pcmChunks = []

    if (gen !== generation) return
    const sec = chunks.reduce((n, a) => n + a.length, 0) / rate
    if (sec < MIN_UTTER_SEC) {
      if (recordingResolve) {
        const resolve = recordingResolve
        recordingResolve = null
        resolve('')
      }
      return
    }

    try {
      const blob = encodeWav(chunks, rate)
      const text = await asr(blob)
      if (gen !== generation) return
      if (recordingResolve) {
        const resolve = recordingResolve
        recordingResolve = null
        resolve(text)
      }
    } catch (e) {
      opts.onError?.(e?.message || String(e))
      if (recordingResolve) {
        const resolve = recordingResolve
        recordingResolve = null
        resolve('')
      }
    }
  }

  // ── ASR ──

  async function asr(blob) {
    const fd = new FormData()
    fd.append('file', blob, 'utterance.wav')
    const resp = await fetch(`${API_BASE}/interview/asr`, {
      method: 'POST',
      body: fd,
    })
    if (!resp.ok) {
      let detail = ''
      try { const j = await resp.json(); detail = j.detail || '' } catch { detail = await resp.text() }
      throw new Error(detail || `ASR HTTP ${resp.status}`)
    }
    const data = await resp.json()
    return (data.text || '').trim()
  }

  // ── VAD tick ──

  function tickLevel(gen) {
    if (gen !== generation || !analyser) return
    const data = new Uint8Array(analyser.fftSize)
    analyser.getByteTimeDomainData(data)
    let sum = 0
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128
      sum += v * v
    }
    const rms = Math.sqrt(sum / data.length)
    audioLevel.value = Math.min(1, rms * 3)

    if (!isRecording.value) return

    const now = performance.now()

    if (!captureNode) {
      if (rms < noiseFloor * 1.35 + 0.01) {
        noiseFloor = noiseFloor * 0.92 + rms * 0.08
      }
      const speakOn = Math.max(SPEAK_ON, noiseFloor * 2.8 + 0.018)
      if (rms >= speakOn) {
        lastLoudAt = now
        beginCapture(gen)
      }
    } else {
      if (rms > speechPeak) speechPeak = rms
      const speechGate = Math.max(
        SPEAK_OFF,
        noiseFloor * 2.2 + 0.012,
        speechPeak * 0.42,
      )
      if (rms >= speechGate) lastLoudAt = now

      const held = now - captureStartedAt
      const silentFor = now - lastLoudAt
      const canEndBySilence = silentFor >= SILENCE_MS && held >= MIN_CAPTURE_MS && speechPeak >= Math.max(SPEAK_ON, noiseFloor * 2)
      const canEndByMax = held >= MAX_CAPTURE_MS
      if (canEndBySilence || canEndByMax) {
        stopRecordingInternal(gen)
      }
    }

    rafId = requestAnimationFrame(() => tickLevel(gen))
  }

  // ── 录音公开 API ──

  async function startRecording() {
    if (isRecording.value) return ''
    generation += 1
    const gen = generation
    isRecording.value = true
    audioLevel.value = 0
    noiseFloor = 0.02
    captureNode = null
    pcmChunks = []

    try {
      await ensureMic()
      tickLevel(gen)
    } catch (e) {
      isRecording.value = false
      opts.onError?.(`麦克风不可用: ${e?.message || String(e)}`)
      return ''
    }

    return new Promise((resolve) => {
      recordingResolve = resolve
    })
  }

  async function stopRecording() {
    if (!isRecording.value) return ''
    const gen = generation
    await stopRecordingInternal(gen)
  }

  async function stopRecordingInternal(gen) {
    if (gen !== generation) return
    if (captureNode) {
      await finishCapture(gen)
    } else {
      stopCapture(false)
      if (recordingResolve) {
        const resolve = recordingResolve
        recordingResolve = null
        resolve('')
      }
    }
    isRecording.value = false
    audioLevel.value = 0
    await cleanupMedia()
  }

  async function cancelRecording() {
    if (!isRecording.value) return
    generation += 1
    stopCapture(false)
    isRecording.value = false
    audioLevel.value = 0
    if (recordingResolve) {
      const resolve = recordingResolve
      recordingResolve = null
      resolve('')
    }
    await cleanupMedia()
  }

  return {
    // 录音（每个组件独立）
    isRecording,
    audioLevel,
    startRecording,
    stopRecording,
    cancelRecording,
    // TTS（模块级单例，所有组件共享）
    isSpeaking,
    speak,
    stopSpeaking,
  }
}
