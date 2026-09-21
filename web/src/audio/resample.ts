// PCM16 线性插值重采样：语音场景足够，纯函数便于单测
// 用于 Opus 下行（解码输出恒为 48k）与播放器目标采样率之间的换算
export function resampleInt16(pcm: Int16Array, fromRate: number, toRate: number): Int16Array<ArrayBuffer> {
  // 项目内所有 PCM 均来自 new Int16Array()（ArrayBuffer-backed），这里的断言是安全的；
  // 同采样率直接返回原数组，避免无谓拷贝
  if (fromRate === toRate) return pcm as Int16Array<ArrayBuffer>
  const outLen = Math.round((pcm.length * toRate) / fromRate)
  const out = new Int16Array(outLen)
  const ratio = fromRate / toRate // 目标每个采样对应源音频中的位置步长
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, pcm.length - 1)
    const v = pcm[i0] + (pcm[i1] - pcm[i0]) * (pos - i0)
    out[i] = Math.max(-32768, Math.min(32767, Math.round(v)))
  }
  return out
}
