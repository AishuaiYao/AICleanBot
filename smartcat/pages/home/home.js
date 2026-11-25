// 设备名/图标/MAC 由设备握手串返回，可能含 & # 空格等字符，必须编码后再拼进 URL
const enc = s => encodeURIComponent(s || '')

// 搜索设备时 TCP 可能连上但设备不回握手，必须有兜底超时
const RADAR_HANDSHAKE_TIMEOUT = 5000
const RADAR_CLOSE_DELAY = 1500

Page({
  data: {
    devices: [],
    showRadar: false,
    showConfirm: false,
    showDelete: false,
    radarStatus: '搜索设备中...',
    esp32IP: '192.168.4.1',
    esp32Port: 5000,
    deviceName: '',
    deviceIcon: '',
    deviceMac: ''
  },

  socket: null,
  _pageAlive: true,
  _radarCloseTimer: null,
  _radarHandshakeTimer: null,

  onLoad() {
    this.loadDevices()
  },

  onShow() {
    this.loadDevices()
  },

  onUnload() {
    // 页面离开后不能再让定时器操作已卸载的页面或弹出 toast
    this._pageAlive = false
    this._clearRadarTimers()
    if (this.connectTimeout) {
      clearTimeout(this.connectTimeout)
      this.connectTimeout = null
    }
    this.connecting = false
    if (this.testSocket) {
      this.testSocket.close()
      this.testSocket = null
    }
    if (this.socket) {
      this.socket.close()
      this.socket = null
    }
  },

  _clearRadarTimers() {
    if (this._radarCloseTimer) {
      clearTimeout(this._radarCloseTimer)
      this._radarCloseTimer = null
    }
    if (this._radarHandshakeTimer) {
      clearTimeout(this._radarHandshakeTimer)
      this._radarHandshakeTimer = null
    }
  },

  _scheduleRadarClose(status) {
    this.setData({ radarStatus: status })
    if (this._radarCloseTimer) return
    this._radarCloseTimer = setTimeout(() => {
      this._radarCloseTimer = null
      this.closeRadar()
    }, RADAR_CLOSE_DELAY)
  },

  _radarFail(reason) {
    if (!this._pageAlive || !this.data.showRadar || this.data.showConfirm) return
    if (this._radarHandshakeTimer) {
      clearTimeout(this._radarHandshakeTimer)
      this._radarHandshakeTimer = null
    }
    if (this._radarCloseTimer) return
    console.log('[Home] ' + reason)
    this._scheduleRadarClose(reason)
  },

  loadDevices() {
    const devices = wx.getStorageSync('devices') || []
    this.setData({ devices })
  },

  saveDevices() {
    wx.setStorageSync('devices', this.data.devices)
  },

  onFabTap() {
    console.log('[Home] 点击搜索按钮')
    this.setData({ showRadar: true, showConfirm: false, radarStatus: '搜索设备中...' })
    this.searchDevice()
  },

  onRadarClose() {
    if (this.data.showConfirm) return
    this.closeRadar()
  },

  closeRadar() {
    this._clearRadarTimers()
    this.setData({ showRadar: false, showConfirm: false, deviceName: '', deviceIcon: '', deviceMac: '' })
    if (this.socket) {
      const old = this.socket
      this.socket = null
      old.close()
    }
  },

  searchDevice() {
    console.log('[Home] ========== 开始搜索设备 ==========')
    console.log('[Home] 目标地址: ' + this.data.esp32IP + ':' + this.data.esp32Port)

    // 重复点击搜索会留下上一个未关闭的 socket 和定时器
    if (this.socket) {
      const old = this.socket
      this.socket = null   // 先摘掉引用，旧 socket 的回调才不会污染新一轮
      old.close()
    }
    this._clearRadarTimers()

    const socket = wx.createTCPSocket()
    if (!socket) {
      console.log('[Home] !!! 创建TCPSocket失败')
      this.setData({ radarStatus: '创建连接失败' })
      return
    }
    console.log('[Home] TCPSocket创建成功')
    this.socket = socket

    // 连上 TCP 但设备始终不回握手时兜底退出
    this._radarHandshakeTimer = setTimeout(() => {
      this._radarHandshakeTimer = null
      this._radarFail('搜索超时')
    }, RADAR_HANDSHAKE_TIMEOUT)

    socket.onConnect(() => {
      if (this.socket !== socket) return
      console.log('[Home] TCP连接成功，发送HELLO握手')
      this.setData({ radarStatus: '握手ing...' })
      socket.write('HELLO\n')
    })

    socket.onMessage(res => {
      if (this.socket !== socket) return
      this._clearRadarTimers()
      const info = String.fromCharCode.apply(null, new Uint8Array(res.message)).trim()
      console.log('[Home] <<< 收到设备响应: ' + info)
      const parts = info.split('|')
      const name = parts[0] || '未知设备'
      const icon = parts[1] || '📦'
      const mac = parts[2] || ''
      console.log('[Home] 设备信息: name=' + name + ', icon=' + icon + ', mac=' + mac)
      this.setData({ radarStatus: '设备已找到!', showConfirm: true, deviceName: name, deviceIcon: icon, deviceMac: mac })
    })

    socket.onClose(() => {
      if (this.socket !== socket) return
      console.log('[Home] TCP连接关闭')
      this._radarFail('连接超时')
    })

    socket.onError((err) => {
      if (this.socket !== socket) return
      console.log('[Home] !!! TCP连接错误:', err)
      this._radarFail('连接失败')
    })

    console.log('[Home] >>> 发起TCP连接...')
    socket.connect({ address: this.data.esp32IP, port: this.data.esp32Port })
    console.log('[Home] ====================================')
  },

  onConfirm() {
    const exists = this.data.devices.find(d => d.mac === this.data.deviceMac)
    if (exists) {
      this._scheduleRadarClose('设备已存在!')
      return
    }
    const newDevice = {
      id: Date.now(),
      name: this.data.deviceName,
      icon: this.data.deviceIcon,
      mac: this.data.deviceMac,
      status: '在线'
    }
    const devices = [...this.data.devices, newDevice]
    this.setData({ devices })
    this.saveDevices()
    this.closeRadar()
  },

  onCardTap(e) {
    const device = e.currentTarget.dataset.device
    console.log('[Home] 点击设备卡片: ' + device.name)

    if (this.connecting) {
      console.log('[Home] !!! 正在连接中，忽略重复点击')
      return
    }

    this.connecting = true

    // createTCPSocket 可能返回空(基础库不支持/资源不足)，此时不能让
    // connecting 与 loading 一直挂着，直接给出失败反馈
    let socket = null
    try {
      socket = wx.createTCPSocket()
    } catch (err) {
      console.log('[Home] !!! 创建TCPSocket异常:', err)
    }
    if (!socket) {
      console.log('[Home] !!! 创建TCPSocket失败')
      this.connecting = false
      wx.showToast({ title: '创建连接失败', icon: 'none' })
      return
    }

    wx.showLoading({ title: '连接中...', mask: true })
    this.testSocket = socket

    // 设置超时：3秒后自动关闭
    this.connectTimeout = setTimeout(() => {
      this.connectTimeout = null
      console.log('[Home] !!! 连接或握手超时')
      this.connecting = false   // 先置位，随后 close 触发的 onClose 不会重复收尾
      wx.hideLoading()
      wx.showToast({ title: '连接超时', icon: 'none' })
      if (this.testSocket) {
        this.testSocket.close()
        this.testSocket = null
      }
    }, 3000)

    socket.onConnect(() => {
      if (!this.connecting) return
      // 超时保留到收到握手响应为止：连上却不回 HELLO 的设备同样会卡住 loading
      console.log('[Home] 设备连接成功，发送HELLO')
      socket.write('HELLO\n')
    })

    socket.onMessage(res => {
      if (!this.connecting) return
      clearTimeout(this.connectTimeout)
      this.connectTimeout = null
      const info = String.fromCharCode.apply(null, new Uint8Array(res.message)).trim()
      console.log('[Home] 设备响应: ' + info)
      wx.hideLoading()
      this.connecting = false
      socket.close()
      this.testSocket = null
      wx.navigateTo({ url: `/pages/device/device?name=${enc(device.name)}&icon=${enc(device.icon)}&mac=${enc(device.mac)}` })
    })

    socket.onError((err) => {
      if (!this.connecting) return
      clearTimeout(this.connectTimeout)
      this.connectTimeout = null
      console.log('[Home] !!! 设备连接错误:', err)
      wx.hideLoading()
      wx.showToast({ title: '无法连接设备', icon: 'none' })
      this.testSocket = null
      this.connecting = false
    })

    socket.onClose(() => {
      // onMessage 主动 close 或页面已卸载时会再次触发，不能重复收尾
      if (!this.connecting) return
      clearTimeout(this.connectTimeout)
      this.connectTimeout = null
      console.log('[Home] 设备连接关闭')
      wx.hideLoading()
      this.testSocket = null
      this.connecting = false
    })

    console.log('[Home] >>> 连接设备: ' + this.data.esp32IP + ':' + this.data.esp32Port)
    socket.connect({ address: this.data.esp32IP, port: this.data.esp32Port })
  },

  onSettingsTap() {
    this.setData({ showDelete: !this.data.showDelete })
  },

  onDebugTap() {
    wx.navigateTo({ url: '/pages/device/device?name=' + enc('模拟设备') + '&icon=' + enc('📦') + '&mac=debug&debug=1' })
  },

  onDeleteDevice(e) {
    const id = e.currentTarget.dataset.id
    const target = this.data.devices.find(d => d.id === id)
    wx.showModal({
      title: '移除设备',
      content: `确定要移除「${(target && target.name) || '该设备'}」吗？`,
      confirmColor: '#ff4d4f',
      success: res => {
        if (!res.confirm) return
        const devices = this.data.devices.filter(d => d.id !== id)
        this.setData({ devices, showDelete: false })
        this.saveDevices()
        wx.showToast({ title: '已移除', icon: 'none' })
      }
    })
  },

  catchTap() {},

  onTabTap(e) {
    const tab = e.currentTarget.dataset.tab
    const pages = {
      home: '/pages/home/home',
      smart: '/pages/smart/smart',
      assistant: '/pages/assistant/assistant',
      my: '/pages/my/my'
    }
    if (pages[tab]) {
      wx.redirectTo({ url: pages[tab] })
    }
  }
})
