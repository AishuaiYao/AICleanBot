const app = getApp()

Page({
  data: {
    imageData: null,
    frameCount: 0,
    streaming: false,
    fps: 0,
    debugMode: false,
    running: false,
    speed: 20,
    savedCount: 0,
    isCollecting: false,
    motorA: 0,
    motorB: 0,
    encoderA: 0,
    encoderB: 0,
    voltage: 0
  },

  lastFrameTime: 0,
  udpSocket: null,
  udpLocalPort: 5002,
  frameBuffer: null,
  frameSize: 19200,

  // 编码器环形缓冲区（1000个增量值）
  encoderBufferSize: 1000,
  encoderA_delta: [],
  encoderB_delta: [],
  encoderBufferIndex: 0,
  encoderBufferFull: false,
  lastEncoderA: 0,
  lastEncoderB: 0,
  lastEncoderValid: false,

  onLoad(options) {
    console.log('[Collect] ========== 页面加载 ==========')
    console.log('[Collect] debug=' + options.debug + ', connected=' + app.globalData.connected)
    
    if (options.debug === '1') {
      this.setData({ debugMode: true, streaming: true })
      this.generateDebugImage()
      return
    }
    
    if (!app.globalData.connected) {
      console.log('[Collect] !!! 设备未连接，返回')
      wx.showToast({ title: '设备未连接', icon: 'none' })
      wx.navigateBack()
      return
    }
    
    console.log('[Collect] 注册回调，初始化UDP')
    this.registerCallbacks()
    this.setupUDP()
  },

  onUnload() {
    console.log('[Collect] 页面卸载')
    this.removeCallbacks()
    
    // 保存编码器数据到全局，供device页面使用
    const count = this.encoderBufferFull ? this.encoderBufferSize : this.encoderBufferIndex
    if (count > 0) {
      const startIdx = this.encoderBufferFull ? this.encoderBufferIndex : 0
      const dataA = []
      const dataB = []
      for (let i = 0; i < count; i++) {
        const idx = (startIdx + i) % this.encoderBufferSize
        dataA.push(this.encoderA_delta[idx] || 0)
        dataB.push(this.encoderB_delta[idx] || 0)
      }
      app.globalData.encoderChartData = { dataA, dataB, count }
      console.log('[Collect] 已保存编码器数据到全局，共' + count + '条')
    }
    
    if (this.udpSocket) {
      app.sendCommand('STOP_STREAM')
      this.udpSocket.close()
      this.udpSocket = null
    }
    this.frameBuffer = null
  },

  // 计算并存储编码器增量
  pushEncoderDelta(currA, currB) {
    if (!this.lastEncoderValid) {
      this.lastEncoderA = currA
      this.lastEncoderB = currB
      this.lastEncoderValid = true
      return
    }

    // 计算增量
    let deltaA = currA - this.lastEncoderA
    let deltaB = currB - this.lastEncoderB

    // 溢出处理：ESP32每32768清零，跳过大跳变
    if (deltaA > 16000 || deltaA < -16000) deltaA = 0
    if (deltaB > 16000 || deltaB < -16000) deltaB = 0

    // 存入环形缓冲区
    this.encoderA_delta[this.encoderBufferIndex] = deltaA
    this.encoderB_delta[this.encoderBufferIndex] = deltaB
    this.encoderBufferIndex = (this.encoderBufferIndex + 1) % this.encoderBufferSize
    if (this.encoderBufferIndex === 0) this.encoderBufferFull = true

    this.lastEncoderA = currA
    this.lastEncoderB = currB
  },

  // 保存柱状图到相册
  onSaveChart() {
    const count = this.encoderBufferFull ? this.encoderBufferSize : this.encoderBufferIndex
    if (count === 0) {
      wx.showToast({ title: '无数据可保存', icon: 'none' })
      return
    }

    wx.showLoading({ title: '正在生成图表...' })

    const width = 1800
    const height = 500
    const padding = 80
    const chartWidth = width - padding * 2
    const chartHeight = height - padding * 2
    const barWidth = Math.max(chartWidth / count, 1)
    const singleBarWidth = Math.max(barWidth / 2 - 1, 1)

    // 收集数据并计算最大值
    const dataA = []
    const dataB = []
    const startIdx = this.encoderBufferFull ? this.encoderBufferIndex : 0
    for (let i = 0; i < count; i++) {
      const idx = (startIdx + i) % this.encoderBufferSize
      dataA.push(this.encoderA_delta[idx] || 0)
      dataB.push(this.encoderB_delta[idx] || 0)
    }
    const maxVal = Math.max(...dataA.map(Math.abs), ...dataB.map(Math.abs), 1)
    const scale = chartHeight / 2 / maxVal

    // 创建 Canvas
    const canvas = wx.createOffscreenCanvas({ type: '2d', width, height })
    const ctx = canvas.getContext('2d')

    // 背景
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, width, height)

    // 标题
    ctx.fillStyle = '#333333'
    ctx.font = 'bold 24px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('Encoder Delta Chart', width / 2, 35)

    // 中线
    ctx.strokeStyle = '#cccccc'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(padding, padding + chartHeight / 2)
    ctx.lineTo(width - padding, padding + chartHeight / 2)
    ctx.stroke()

    // 绘制柱状图
    for (let i = 0; i < count; i++) {
      const x = padding + i * barWidth
      const barH = Math.abs(dataA[i]) * scale
      const barHB = Math.abs(dataB[i]) * scale

      // 左电机(红色)
      ctx.fillStyle = '#e74c3c'
      if (dataA[i] >= 0) {
        ctx.fillRect(x, padding + chartHeight / 2 - barH, singleBarWidth, barH)
      } else {
        ctx.fillRect(x, padding + chartHeight / 2, singleBarWidth, barH)
      }

      // 右电机(蓝色)
      ctx.fillStyle = '#3498db'
      if (dataB[i] >= 0) {
        ctx.fillRect(x + singleBarWidth + 1, padding + chartHeight / 2 - barHB, singleBarWidth, barHB)
      } else {
        ctx.fillRect(x + singleBarWidth + 1, padding + chartHeight / 2, singleBarWidth, barHB)
      }
    }

    // 图例
    ctx.fillStyle = '#e74c3c'
    ctx.fillRect(width - 140, 15, 16, 16)
    ctx.fillStyle = '#333333'
    ctx.font = '14px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText('Motor A', width - 120, 28)

    ctx.fillStyle = '#3498db'
    ctx.fillRect(width - 140, 38, 16, 16)
    ctx.fillStyle = '#333333'
    ctx.fillText('Motor B', width - 120, 51)

    // Y轴标签
    ctx.fillStyle = '#666666'
    ctx.font = '12px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(maxVal.toFixed(0), padding - 5, padding + 10)
    ctx.fillText('0', padding - 5, padding + chartHeight / 2 + 4)
    ctx.fillText((-maxVal).toFixed(0), padding - 5, padding + chartHeight - 2)

    // X轴标签
    ctx.textAlign = 'center'
    ctx.fillText('1', padding, height - padding + 20)
    ctx.fillText(count.toString(), width - padding, height - padding + 20)

    // 保存到相册
    wx.canvasToTempFilePath({
      canvas,
      success: (res) => {
        wx.hideLoading()
        wx.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => {
            wx.showToast({ title: '已保存到相册', icon: 'success' })
            console.log('[Chart] 保存成功')
          },
          fail: (err) => {
            console.log('[Chart] 保存失败:', err)
            wx.showToast({ title: '保存失败', icon: 'none' })
          }
        })
      },
      fail: (err) => {
        wx.hideLoading()
        console.log('[Chart] 生成失败:', err)
        wx.showToast({ title: '生成失败', icon: 'none' })
      }
    })
  },

  registerCallbacks() {
    this.onMessageBound = this.onMessage.bind(this)
    this.onCloseBound = this.onClose.bind(this)
    this.onErrorBound = this.onError.bind(this)
    app.addMessageCallback(this.onMessageBound)
    app.addCloseCallback(this.onCloseBound)
    app.addErrorCallback(this.onErrorBound)
  },

  removeCallbacks() {
    app.removeMessageCallback(this.onMessageBound)
    app.removeCloseCallback(this.onCloseBound)
    app.removeErrorCallback(this.onErrorBound)
  },

  onMessage(res) {
    const bytes = new Uint8Array(res.message)
    const str = String.fromCharCode(...bytes.subarray(0, Math.min(bytes.length, 50)))
    console.log('[Collect] TCP消息: ' + str)
    
    if (str.includes('UDP_OK')) {
      console.log('[Collect] UDP就绪，发送STREAM')
      app.sendCommand('STREAM')
      this.setData({ streaming: true })
      return
    }
    
    if (str.includes('UDP_NOT_READY')) {
      console.log('[Collect] UDP未就绪')
      wx.showToast({ title: 'UDP初始化失败', icon: 'none' })
    }
  },

  onClose() {
    console.log('[Collect] TCP连接已关闭')
    this.setData({ streaming: false })
  },

  onError(err) {
    console.log('[Collect] TCP连接错误:', err)
    wx.showToast({ title: '连接断开', icon: 'none' })
    this.setData({ streaming: false })
  },

  setupUDP() {
    console.log('========== UDP初始化 ==========')
    
    const udp = wx.createUDPSocket()
    if (!udp) {
      console.log('[Collect] 创建UDP失败')
      wx.showToast({ title: 'UDP创建失败', icon: 'none' })
      return
    }
    this.udpSocket = udp
    app.setUDPSocket(udp)

    udp.onMessage((res) => {
      this.onReceiveUDPData(res.message)
    })

    udp.onError((err) => {
      console.log('[Collect] UDP错误:', err)
    })

    const port = udp.bind(this.udpLocalPort)
    console.log('[Collect] UDP绑定端口: ' + port)
    console.log('================================')
    
    app.sendCommand('UDP_HELLO:' + port)
    
    const helloMsg = 'HELLO_UDP'
    udp.send({
      address: app.globalData.esp32IP,
      port: 5001,
      message: helloMsg
    })
    console.log('[Collect] 发送HELLO_UDP到ESP32')
  },

  lastMsgTime: 0,

  onReceiveUDPData(data) {
    const t0 = Date.now()

    if (this.lastMsgTime > 0) {
      const gap = t0 - this.lastMsgTime
      if (gap > 200) {
        console.log('[GAP] onMessage空闲+' + gap + 'ms')
      }
    }
    this.lastMsgTime = t0

    const bytes = new Uint8Array(data)
    if (bytes.length < 4) {

      console.log('[UDP] 数据太短:', bytes.length)
      return
    }
    
    // 解析分片协议头
    const frameNum = (bytes[0] << 8) | bytes[1]    // 帧号
    const totalChunks = bytes[2]                    // 总分片数
    const chunkIndex = bytes[3]                     // 当前分片索引
    let chunkData
    
    // 第一分片包含电压、电机PWM值和编码器脉冲数
    if (chunkIndex === 0 && bytes.length >= 11) {
      const voltageRaw = bytes[4]
      const voltage = (voltageRaw / 10).toFixed(1)
      const motorA = Math.round(bytes[5] * 100 / 255)
      const motorB = Math.round(bytes[6] * 100 / 255)
      const encoderA = (bytes[7] << 8) | bytes[8]
      const encoderB = (bytes[9] << 8) | bytes[10]
      this.setData({ voltage, motorA, motorB, encoderA, encoderB })

      // 计算编码器增量并存储
      this.pushEncoderDelta(encoderA, encoderB)

      chunkData = bytes.slice(11)
    } else {
      chunkData = bytes.slice(4)
    }
    
    // 初始化或切换帧缓冲区
    const now = Date.now()
    if (!this.frameBuffer || this.frameBuffer.frameNum !== frameNum) {
      this.frameBuffer = {
        frameNum: frameNum,
        totalChunks: totalChunks,
        chunks: new Array(totalChunks),
        receivedCount: 0,
        startTime: now
      }
    }
    
    // 存储分片
    if (!this.frameBuffer.chunks[chunkIndex]) {
      this.frameBuffer.chunks[chunkIndex] = chunkData
      this.frameBuffer.receivedCount++
      console.log('[Chunk] 帧' + frameNum + ' 片' + (chunkIndex + 1) + '/' + totalChunks + ', 距首片+' + (now - this.frameBuffer.startTime) + 'ms')
    }
    
    // 检查是否收齐所有分片
    if (this.frameBuffer.receivedCount === this.frameBuffer.totalChunks) {
      const tAssembleStart = Date.now()
      const grayData = this.assembleFrame()
      const tAssembleEnd = Date.now()

      if (grayData) {
        const now = Date.now()
        if (this.lastFrameTime > 0) {
          const delta = now - this.lastFrameTime
          const fps = delta > 0 ? Math.round(1000 / delta) : 0
          this.setData({ fps })
        }
        this.lastFrameTime = now

        const frameCount = this.data.frameCount + 1
        this.setData({ frameCount })

        console.log('[Assemble] 帧' + frameCount + '(ESP32帧' + frameNum + '): 组装耗时' + (tAssembleEnd - tAssembleStart) + 'ms, 距首片' + (tAssembleEnd - this.frameBuffer.startTime) + 'ms, 帧间隔' + (this.data.fps ? Math.round(1000/this.data.fps) : '?') + 'ms')

        this.processImage(grayData, tAssembleEnd)
      }

      this.frameBuffer = null
    }
  },

  assembleFrame() {
    if (!this.frameBuffer || this.frameBuffer.receivedCount !== this.frameBuffer.totalChunks) {
      return null
    }
    
    const grayData = new Uint8Array(this.frameSize)
    let offset = 0
    
    for (let i = 0; i < this.frameBuffer.totalChunks; i++) {
      const chunk = this.frameBuffer.chunks[i]
      if (chunk) {
        grayData.set(chunk, offset)
        offset += chunk.length
      }
    }
    
    return grayData
  },

  processImage(grayData, tAssembleEnd) {
    const t0 = Date.now()
    console.log('[Process] 进入processImage, 距组装完成+' + (t0 - tAssembleEnd) + 'ms')

    const width = 160
    const height = 120
    const rgbaData = new Uint8ClampedArray(width * height * 4)

    for (let i = 0; i < grayData.length; i++) {
      rgbaData[i * 4] = grayData[i]
      rgbaData[i * 4 + 1] = grayData[i]
      rgbaData[i * 4 + 2] = grayData[i]
      rgbaData[i * 4 + 3] = 255
    }

    const t1 = Date.now()

    const canvas = wx.createOffscreenCanvas({ type: '2d', width, height })
    const ctx = canvas.getContext('2d')
    const imgData = ctx.createImageData(width, height)
    imgData.data.set(rgbaData)
    ctx.putImageData(imgData, 0, 0)

    const t2 = Date.now()
    const frameCount = this.data.frameCount

    console.log('[Draw] 帧' + frameCount + ': RGBA+' + (t1 - t0) + 'ms Canvas+' + (t2 - t1) + 'ms | 准备转tempFile')

    wx.canvasToTempFilePath({
      canvas,
      success: (res) => {
        const t3 = Date.now()
        this.setData({ imageData: res.tempFilePath })
        console.log('[Render] 帧' + frameCount + ': tempFile耗时' + (t3 - t2) + 'ms, 总渲染' + (t3 - t0) + 'ms')

        if (frameCount % 10 === 1 && !this.data.debugMode && this.data.isCollecting) {
          this.saveImage(res.tempFilePath)
        }
      }
    })
  },

  saveImage(tempFilePath) {
    let images = wx.getStorageSync('savedImages') || []
    if (images.length >= 500) {
      console.log('[Save] 已达500张上限，跳过保存')
      return
    }

    wx.saveFile({
      tempFilePath,
      success: (res) => {
        images.unshift({
          path: res.savedFilePath,
          time: new Date().toLocaleString(),
          uploaded: false
        })
        wx.setStorageSync('savedImages', images)
        const savedCount = this.data.savedCount + 1
        this.setData({ savedCount })
        console.log('[Save] 已保存第' + savedCount + '幅图像到缓存，共' + images.length + '张')
      },
      fail: (err) => {
        console.log('[Save] 保存失败:', err)
      }
    })
  },

  onLeft() {
    console.log('[Collect] >>> 左转按钮')
    if (this.data.debugMode) return
    app.sendCommand('MOTOR_LEFT')
  },

  onRight() {
    console.log('[Collect] >>> 右转按钮')
    if (this.data.debugMode) return
    app.sendCommand('MOTOR_RIGHT')
  },

  onStop() {
    console.log('[Collect] >>> 恢复直行')
    if (this.data.debugMode) return
    app.sendCommand('MOTOR_FORWARD')
  },

  onStartStop() {
    const running = !this.data.running
    this.setData({ running })
    if (this.data.debugMode) return
    if (running) {
      app.sendCommand('START:' + this.data.speed)
      this.setData({ isCollecting: true })
    } else {
      app.sendCommand('STOP')
      this.setData({ isCollecting: false })
    }
  },

  onSpeedUp() {
    if (this.data.speed >= 100) return
    const speed = this.data.speed + 1
    this.setData({ speed })
    if (this.data.running && !this.data.debugMode) {
      app.sendCommand('SPEED:' + speed)
    }
  },

  onSpeedDown() {
    if (this.data.speed <= 0) return
    const speed = this.data.speed - 1
    this.setData({ speed })
    if (this.data.running && !this.data.debugMode) {
      app.sendCommand('SPEED:' + speed)
    }
  },

  generateDebugImage() {
    const width = 160
    const height = 120
    const rgbaData = new Uint8ClampedArray(width * height * 4)
    
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4
        const gray = Math.floor((x / width) * 255)
        rgbaData[i] = gray
        rgbaData[i + 1] = gray
        rgbaData[i + 2] = gray
        rgbaData[i + 3] = 255
      }
    }
    
    const canvas = wx.createOffscreenCanvas({ type: '2d', width, height })
    const ctx = canvas.getContext('2d')
    const imgData = ctx.createImageData(width, height)
    imgData.data.set(rgbaData)
    ctx.putImageData(imgData, 0, 0)
    
    wx.canvasToTempFilePath({
      canvas,
      success: (res) => {
        this.setData({ imageData: res.tempFilePath })
      }
    })
  }
})
