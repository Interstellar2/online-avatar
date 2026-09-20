import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../src/App.vue'
import { installFakeAudioContext, installFakeWebSocket, mockFetchJson } from './helpers'

let FakeWS: ReturnType<typeof installFakeWebSocket>

beforeEach(() => {
  FakeWS = installFakeWebSocket()
  installFakeAudioContext()
  mockFetchJson({ status: 'ok', dashscope_configured: true })
})

describe('App.vue 冒烟', () => {
  it('挂载后显示未连接，点击连接后状态更新', async () => {
    const wrapper = mount(App)
    expect(wrapper.text()).toContain('未连接')

    await wrapper.find('button').trigger('click') // 第一个按钮是连接
    const ws = FakeWS.instances[0]
    expect(ws.url).toContain('/ws/avatar/')
    ws.simulateOpen()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('断开')
  })

  it('连接后可发送文字并渲染回复', async () => {
    const wrapper = mount(App)
    await wrapper.find('button').trigger('click')
    const ws = FakeWS.instances[0]
    ws.simulateOpen()
    await wrapper.vm.$nextTick()

    const input = wrapper.find('input[type="text"]')
    await input.setValue('你好')
    await wrapper.find('.footer button:last-child').trigger('click') // 发送
    expect(ws.sentJson()).toContainEqual({ type: 'text', content: '你好' })

    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    ws.simulateJson({ type: 'llm_token', text: '你好呀' })
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('你好呀')
    expect(wrapper.text()).toContain('正在回答')
  })

  it('服务端未配密钥时显示提示', async () => {
    mockFetchJson({ status: 'ok', dashscope_configured: false })
    const wrapper = mount(App)
    await new Promise((r) => setTimeout(r, 0)) // 等 onMounted 的 fetch
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('DASHSCOPE_API_KEY')
  })
})
