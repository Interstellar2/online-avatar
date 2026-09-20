// 麦克风采集：AudioContext 重采样到 16kHz PCM16，以二进制帧发送
// 注：ScriptProcessor 已废弃但兼容性最好，测试用途够用；生产可换 AudioWorklet

import { ref } from 'vue'

const TARGET_RATE = 16000
const BUFFER_SIZE = 4096

export function useMicCapture(onFrame: (pcm: Int16Array) => void) {
  const isCapturing = ref(false)

  let ctx: AudioContext | null = null
  let stream: MediaStream | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let node: ScriptProcessorNode | null = null

  const start = async () => {
    if (isCapturing.value) return
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    ctx = new AudioContext()
    source = ctx.createMediaStreamSource(stream)
    node = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1)
    node.onaudioprocess = (e) => {
      const pcm = downsampleToInt16(e.inputBuffer.getChannelData(0), ctx!.sampleRate)
      if (pcm.length) onFrame(pcm)
    }
    source.connect(node)
    node.connect(ctx.destination)
    isCapturing.value = true
  }

  const stop = () => {
    node?.disconnect()
    source?.disconnect()
    stream?.getTracks().forEach((t) => t.stop())
    ctx?.close()
    node = source = null
    stream = null
    ctx = null
    isCapturing.value = false
  }

  return { isCapturing, start, stop }
}

export function downsampleToInt16(samples: Float32Array, srcRate: number): Int16Array {
  const ratio = srcRate / TARGET_RATE
  const outLen = Math.floor(samples.length / ratio)
  const out = new Int16Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, samples.length - 1)
    const v = samples[i0] + (samples[i1] - samples[i0]) * (pos - i0)
    out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)))
  }
  return out
}
