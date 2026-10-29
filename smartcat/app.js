App({
  globalData: {
    tcpSocket: null,
    udpSocket: null,
    connected: false,
    esp32IP: '192.168.4.1',
    esp32Port: 5000,
    udpLocalPort: 5001,
    messageCallbacks: [],
    closeCallbacks: [],
    errorCallbacks: [],
    otaMessageCallback: null,
    // 微信云开发环境 ID：仓库中为占位符 **，请改成你自己的（微信开发者工具 → 云开发 → 环境 → 环境 ID）
    cloudEnv: '**',
    // 云存储路径前缀，同样替换成你自己的环境 ID 与 bucket
    cloudEnvPrefix: '**'
  },

  onLaunch() {
    console.log('[SmartCat] 小程序启动')
    
    if (wx.cloud) {
      wx.cloud.init({
        env: '**',   // 改成你自己的云环境 ID
        traceUser: true
      })
      console.log('[SmartCat] 云开发初始化成功')
    } else {
      console.log('[SmartCat] 请使用 2.2.3 或以上的基础库以使用云能力')
    }
  },

  connectTCP(callback) {
    if (this.globalData.tcpSocket && this.globalData.connected) {
      console.log('[App] TCP已连接，复用现有连接')
      callback && callback(true)
      return true
    }

    console.log('[App] ========== 创建新TCP连接 ==========')
    console.log('[App] 目标: ' + this.globalData.esp32IP + ':' + this.globalData.esp32Port)
    
    const socket = wx.createTCPSocket()
    if (!socket) {
      console.log('[App] !!! 创建TCPSocket失败')
      callback && callback(false)
      return false
    }
    console.log('[App] TCPSocket创建成功')

    this.globalData.tcpSocket = socket

    socket.onConnect(() => {
      console.log('[App] TCP连接成功，发送HELLO')
      socket.write('HELLO\n')
    })

    socket.onMessage((res) => {
      if (this.globalData.otaMessageCallback) {
        this.globalData.otaMessageCallback(res)
        return
      }
      this.globalData.messageCallbacks.forEach(cb => cb(res))
    })

    socket.onClose(() => {
      console.log('[App] TCP连接关闭')
      this.globalData.connected = false
      this.globalData.tcpSocket = null
      this.globalData.closeCallbacks.forEach(cb => cb())
    })

    socket.onError((err) => {
      console.log('[App] !!! TCP错误:', err)
      this.globalData.connected = false
      this.globalData.tcpSocket = null
      this.globalData.errorCallbacks.forEach(cb => cb(err))
    })

    console.log('[App] >>> 发起连接...')
    socket.connect({ 
      address: this.globalData.esp32IP, 
      port: this.globalData.esp32Port 
    })
    console.log('[App] ====================================')
    return true
  },

  setConnected(connected) {
    this.globalData.connected = connected
  },

  sendCommand(cmd) {
    console.log('[App] >>> 发送命令: ' + cmd)
    if (!this.globalData.tcpSocket) {
      console.log('[App] !!! TCP未连接，无法发送')
      return false
    }
    const msg = cmd + '\n'
    const buffer = new ArrayBuffer(msg.length)
    const view = new Uint8Array(buffer)
    for (let i = 0; i < msg.length; i++) {
      view[i] = msg.charCodeAt(i)
    }
    this.globalData.tcpSocket.write(buffer)
    return true
  },

  sendBinary(data) {
    if (!this.globalData.tcpSocket) {
      console.log('[App] !!! TCP未连接，无法发送二进制数据')
      return false
    }
    this.globalData.tcpSocket.write(data)
    return true
  },

  setOTACallback(cb) {
    this.globalData.otaMessageCallback = cb
  },

  clearOTACallback() {
    this.globalData.otaMessageCallback = null
  },

  disconnectTCP() {
    console.log('[App] ========== 断开连接 ==========')
    if (this.globalData.udpSocket) {
      this.globalData.udpSocket.close()
      this.globalData.udpSocket = null
      console.log('[App] UDP已关闭')
    }
    if (this.globalData.tcpSocket) {
      console.log('[App] 发送STOP命令')
      this.sendCommand('STOP')
      this.globalData.tcpSocket.close()
      this.globalData.tcpSocket = null
      console.log('[App] TCP已关闭')
    }
    this.globalData.connected = false
    this.globalData.messageCallbacks = []
    this.globalData.closeCallbacks = []
    this.globalData.errorCallbacks = []
    console.log('[App] ====================================')
  },

  addMessageCallback(callback) {
    this.globalData.messageCallbacks.push(callback)
  },

  removeMessageCallback(callback) {
    const index = this.globalData.messageCallbacks.indexOf(callback)
    if (index > -1) {
      this.globalData.messageCallbacks.splice(index, 1)
    }
  },

  addCloseCallback(callback) {
    this.globalData.closeCallbacks.push(callback)
  },

  removeCloseCallback(callback) {
    const index = this.globalData.closeCallbacks.indexOf(callback)
    if (index > -1) {
      this.globalData.closeCallbacks.splice(index, 1)
    }
  },

  addErrorCallback(callback) {
    this.globalData.errorCallbacks.push(callback)
  },

  removeErrorCallback(callback) {
    const index = this.globalData.errorCallbacks.indexOf(callback)
    if (index > -1) {
      this.globalData.errorCallbacks.splice(index, 1)
    }
  },

  setUDPSocket(socket) {
    this.globalData.udpSocket = socket
  }
})
