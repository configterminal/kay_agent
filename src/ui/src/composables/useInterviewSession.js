/**
 * 面试语音会话 — 开麦常听 / VAD 切句 / ASR / TTS / barge-in。
 * 主路径为语音；不触碰 Avatar DOM；只暴露 state 与 audioLevel。
 */

const API_ORIGIN = 'http://localhost:8000'
const API_BASE = `${API_ORIGIN}/api`

/** @typedef {'idle'|'boot'|'listening'|'capturing'|'transcribing'|'thinking'|'speaking'|'error'} InterviewState */

/** 绝对下限（相对噪声底会再抬高） */
const SPEAK_ON = 0.045
const SPEAK_OFF = 0.028
const BARGE_ON = 0.2
/** 说完后静音多久算一句结束（相对能量判定） */
const SILENCE_MS = 700
const MIN_CAPTURE_MS = 400
const MAX_CAPTURE_MS = 20000
const BARGE_HOLD_MS = 180
/** 最短有效语音（秒），过短丢弃回 listening */
const MIN_UTTER_SEC = 0.3

/**
 * @param {{
 *   sendTurn: (text: string) => Promise<string>,
 *   onError?: (msg: string) => void,
 * }} opts
 */
export function createInterviewSession(opts) {
  /** @type {import('vue').Ref<InterviewState> | { value: InterviewState }} */
  let state = { value: 'idle' }
  let audioLevel = { value: 0 }
  let captionInterviewer = { value: '' }
  let captionUser = { value: '' }
  let errorDetail = { value: '' }
  let ttsEngine = { value: '' }
  let micLive = { value: false }

  /** 外部可注入 ref */
  function bindRefs(refs) {
    if (refs.state) state = refs.state
    if (refs.audioLevel) audioLevel = refs.audioLevel
    if (refs.captionInterviewer) captionInterviewer = refs.captionInterviewer
    if (refs.captionUser) captionUser = refs.captionUser
    if (refs.errorDetail) errorDetail = refs.errorDetail
    if (refs.ttsEngine) ttsEngine = refs.ttsEngine
    if (refs.micLive) micLive = refs.micLive
  }

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
  let bargeHoldStart = 0
  /** 环境噪声底（listening 时慢速估计） */
  let noiseFloor = 0.02
  /** 本句语音峰值，用于相对静音判定 */
  let speechPeak = 0
  let speakingAudio = null
  let speakingUrl = null
  let running = false
  let generation = 0

  function setState(s) {
    state.value = s
  }

  function setError(msg) {
    errorDetail.value = msg || ''
    setState('error')
    opts.onError?.(msg)
  }

  async function checkReady() {
    const resp = await fetch(`${API_BASE}/interview/speech/ready`)
    if (!resp.ok) throw new Error(`speech/ready HTTP ${resp.status}`)
    const data = await resp.json()
    if (!data.ready) throw new Error(data.detail || '语音未就绪')
    return data
  }

  /** 进场前发现并选定 TTS 引擎（不迁 Embedding） */
  async function prepareSpeech() {
    const resp = await fetch(`${API_BASE}/interview/speech/prepare`, {
      method: 'POST',
    })
    if (!resp.ok) throw new Error(`speech/prepare HTTP ${resp.status}`)
    const data = await resp.json()
    ttsEngine.value = data.selected || 'edge'
    return data
  }

  async function releaseSpeech() {
    try {
      await fetch(`${API_BASE}/interview/speech/release`, { method: 'POST' })
    } catch { /* ignore */ }
    ttsEngine.value = ''
  }

  async function start(openingText = '') {
    if (running) return
    running = true
    generation += 1
    const gen = generation
    setState('boot')
    errorDetail.value = ''
    captionUser.value = ''
    captionInterviewer.value = ''
    micLive.value = false

    try {
      await checkReady()
      await prepareSpeech()
      // 关闭 AGC：否则静音被放大，VAD 永远判「还在说」
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          channelCount: 1,
        },
      })
      audioCtx = new AudioContext()
      // 部分浏览器需 resume 后 Analyser / 录音才有数据
      if (audioCtx.state === 'suspended') {
        await audioCtx.resume()
      }
      captureSampleRate = audioCtx.sampleRate || 48000
      analyser = audioCtx.createAnalyser()
      analyser.fftSize = 2048
      micSource = audioCtx.createMediaStreamSource(stream)
      micSource.connect(analyser)
      micLive.value = true
      tickLevel(gen)

      // 长文本多半是聊天气泡里的设定/画像，禁止整段 TTS
      const open = (openingText || '').trim()
      const useCachedOpen = open.length > 0 && open.length <= 80
      if (useCachedOpen) {
        await speak(open, gen)
      } else {
        const reply = await runTurn(
          '我已进入全屏面试场。请你作为面试官用一两句介绍自己，然后请我做简短自我介绍。'
          + '不要复述学员画像、简历设定、长篇规则或上一轮聊天长文。',
          gen,
        )
        if (gen !== generation) return
        if (reply) await speak(reply, gen)
      }
      if (gen === generation && running) setState('listening')
    } catch (e) {
      running = false
      micLive.value = false
      setError(e?.message || String(e))
      await cleanupMedia()
    }
  }

  async function stop() {
    generation += 1
    running = false
    stopCapture(false)
    stopSpeaking()
    await releaseSpeech()
    await cleanupMedia()
    setState('idle')
    audioLevel.value = 0
    micLive.value = false
  }

  async function cleanupMedia() {
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = 0
    }
    teardownCaptureNode()
    try {
      micSource?.disconnect()
    } catch { /* ignore */ }
    micSource = null
    analyser = null
    if (audioCtx) {
      try {
        await audioCtx.close()
      } catch { /* ignore */ }
      audioCtx = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    micLive.value = false
  }

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

    const now = performance.now()
    const st = state.value

    if (st === 'listening') {
      // 安静时更新噪声底，开口阈值随环境抬高
      if (rms < noiseFloor * 1.35 + 0.01) {
        noiseFloor = noiseFloor * 0.92 + rms * 0.08
      }
      const speakOn = Math.max(SPEAK_ON, noiseFloor * 2.8 + 0.018)
      if (rms >= speakOn) {
        lastLoudAt = now
        beginCapture(gen)
      }
    } else if (st === 'capturing') {
      if (rms > speechPeak) speechPeak = rms
      // 相对峰值 + 噪声底：环境底噪不再把 lastLoudAt 一直刷掉
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
        finishCapture(gen)
      }
    } else if (st === 'speaking') {
      // 交流打断：持续大声才认，降低扬声器回声误触
      const bargeOn = Math.max(BARGE_ON, noiseFloor * 4 + 0.08)
      if (rms >= bargeOn) {
        if (!bargeHoldStart) bargeHoldStart = now
        else if (now - bargeHoldStart >= BARGE_HOLD_MS) {
          bargeHoldStart = 0
          stopSpeaking()
          beginCapture(gen)
        }
      } else {
        bargeHoldStart = 0
      }
    }

    rafId = requestAnimationFrame(() => tickLevel(gen))
  }

  function teardownCaptureNode() {
    if (captureNode) {
      try {
        captureNode.disconnect()
      } catch { /* ignore */ }
      captureNode.onaudioprocess = null
      captureNode = null
    }
    if (silentGain) {
      try {
        silentGain.disconnect()
      } catch { /* ignore */ }
      silentGain = null
    }
  }

  /**
   * 用 ScriptProcessor 录 PCM → WAV，避免 webm 无 ffmpeg 时 FunASR 解不开。
   */
  function beginCapture(gen) {
    if (gen !== generation || !stream || !audioCtx || !micSource || captureNode) return
    pcmChunks = []
    speechPeak = 0
    captureStartedAt = performance.now()
    lastLoudAt = captureStartedAt
    captureSampleRate = audioCtx.sampleRate || captureSampleRate

    try {
      // 缓冲越大延迟略增，但切句更稳；单声道
      captureNode = audioCtx.createScriptProcessor(4096, 1, 1)
      silentGain = audioCtx.createGain()
      silentGain.gain.value = 0
      captureNode.onaudioprocess = (ev) => {
        if (state.value !== 'capturing' && state.value !== 'speaking') return
        // barge-in 后立刻进入 capturing；speaking 末尾几帧可忽略
        if (state.value !== 'capturing') return
        const input = ev.inputBuffer.getChannelData(0)
        pcmChunks.push(new Float32Array(input))
      }
      micSource.connect(captureNode)
      captureNode.connect(silentGain)
      silentGain.connect(audioCtx.destination)
    } catch (e) {
      setError(`无法录音: ${e.message}`)
      teardownCaptureNode()
      return
    }
    setState('capturing')
  }

  function stopCapture(keepChunks) {
    teardownCaptureNode()
    if (!keepChunks) pcmChunks = []
  }

  function finishCapture(gen) {
    if (gen !== generation || !captureNode) return
    setState('transcribing')
    const chunks = pcmChunks
    const rate = captureSampleRate
    stopCapture(true)
    pcmChunks = []

    ;(async () => {
      if (gen !== generation || !running) return
      const sec = chunks.reduce((n, a) => n + a.length, 0) / rate
      if (sec < MIN_UTTER_SEC) {
        setState('listening')
        return
      }
      try {
        const blob = encodeWav(chunks, rate)
        const text = await asr(blob)
        if (gen !== generation) return
        captionUser.value = text
        if (!text.trim()) {
          setState('listening')
          return
        }
        const reply = await runTurn(text, gen)
        if (gen !== generation) return
        if (reply) await speak(reply, gen)
        if (gen === generation && running) setState('listening')
      } catch (e) {
        if (gen === generation) setError(e?.message || String(e))
      }
    })()
  }

  async function asr(blob) {
    const fd = new FormData()
    fd.append('file', blob, 'utterance.wav')
    const resp = await fetch(`${API_BASE}/interview/asr`, {
      method: 'POST',
      body: fd,
    })
    if (!resp.ok) {
      let detail = ''
      try {
        const j = await resp.json()
        detail = j.detail || ''
      } catch {
        detail = await resp.text()
      }
      throw new Error(detail || `ASR HTTP ${resp.status}`)
    }
    const data = await resp.json()
    return (data.text || '').trim()
  }

  async function runTurn(text, gen) {
    if (gen !== generation) return ''
    setState('thinking')
    captionUser.value = text
    const reply = await opts.sendTurn(text)
    return (reply || '').trim()
  }

  /**
   * 播报面试官文本（可 barge-in）。
   */
  async function speak(text, gen = generation) {
    const plain = stripForSpeech(text)
    if (!plain || gen !== generation) return
    captionInterviewer.value = plain
    setState('speaking')
    bargeHoldStart = 0

    // TTS 期间确保分析器仍在跑（AudioContext 可能被挂起）
    if (audioCtx?.state === 'suspended') {
      try {
        await audioCtx.resume()
      } catch { /* ignore */ }
    }

    const resp = await fetch(`${API_BASE}/interview/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: plain }),
    })
    if (!resp.ok) {
      let detail = ''
      try { detail = (await resp.json()).detail || '' } catch { detail = await resp.text() }
      throw new Error(`TTS HTTP ${resp.status}${detail ? `: ${String(detail).slice(0, 160)}` : ''}`)
    }
    const buf = await resp.arrayBuffer()
    if (gen !== generation) return

    stopSpeaking()
    const mime = resp.headers.get('content-type') || 'audio/mpeg'
    speakingUrl = URL.createObjectURL(new Blob([buf], { type: mime.split(';')[0].trim() }))
    speakingAudio = new Audio(speakingUrl)
    await new Promise((resolve, reject) => {
      const done = () => {
        speakingAudio = null
        resolve()
      }
      speakingAudio.onended = done
      speakingAudio.onerror = () => {
        speakingAudio = null
        reject(new Error('TTS 播放失败'))
      }
      // 供 stopSpeaking / barge-in 提前结束
      speakingAudio._interviewResolve = done
      speakingAudio.play().catch(reject)
    }).catch((e) => {
      if (gen === generation) throw e
    })
  }

  function stopSpeaking() {
    if (speakingAudio) {
      const resolve = speakingAudio._interviewResolve
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
  }

  /**
   * 调试用：跳过 ASR，直接提交学员文本（等同说完一句）。
   * 默认 UI 不展示；仅 localStorage.interview_debug=1 时可用。
   */
  async function submitText(text) {
    const plain = String(text || '').trim()
    if (!plain || !running) return
    const gen = generation
    stopSpeaking()
    stopCapture(false)
    try {
      const reply = await runTurn(plain, gen)
      if (gen !== generation) return
      if (reply) await speak(reply, gen)
      if (gen === generation && running) setState('listening')
    } catch (e) {
      if (gen === generation) setError(e?.message || String(e))
    }
  }

  /** 用户点「说完了」：立刻结束本句并送 ASR（VAD 兜底） */
  function finishNow() {
    if (!running) return
    const gen = generation
    if (state.value === 'capturing') {
      finishCapture(gen)
      return
    }
    if (state.value === 'listening') {
      // 尚未开口：忽略
      return
    }
  }

  return {
    bindRefs,
    start,
    stop,
    submitText,
    finishNow,
    get state() {
      return state.value
    },
  }
}

/** Float32 PCM 片段 → 16-bit mono WAV Blob */
export function encodeWav(chunks, sampleRate) {
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

function writeStr(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i))
  }
}

/** 去掉 Markdown，便于 TTS */
export function stripForSpeech(md) {
  return String(md || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`]+`/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
    .replace(/[#>*_~|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 1200)
}
