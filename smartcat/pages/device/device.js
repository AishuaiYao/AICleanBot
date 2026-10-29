const app = getApp()

Page({
  data: {
    connected: false,
    connecting: true,
    deviceName: '',
    debugMode: false,
    capturing: false,
    imageData: null,
    savedImages: [],
    imageCount: 0,
    progress: 0,
    logMsgs: []
  },

  receiveBuffer: null,
  expectedLength: 0,
  receiveOffset: 0,
  chunkCount: 0,
  headerBuffer: [],

  log(msg) {
    const time = new Date().toLocaleTimeString()
    console.log(time + ' | ' + msg)
    const msgs = this.data.logMsgs
    msgs.unshift(msg)
    if (msgs.length > 50) msgs.pop()
    this.setData({ logMsgs: msgs })
  },

  onLoad(options) {
    const deviceName = options.name || '未知设备'
    const debugMode = options.debug === '1'
    this.setData({ deviceName, debugMode })
    wx.setNavigationBarTitle({ title: deviceName })
    this.log('页面加载: ' + deviceName + (debugMode ? ' [调试模式]' : ''))
    this.loadSavedImages()
    if (!debugMode) {
      this.registerCallbacks()
      this.connectDevice()
    } else {
      this.setData({ connected: true, connecting: false })
    }
  },

  onShow() {
    this.log('页面显示')
    if (!this.data.debugMode) {
      this.setData({ connected: app.globalData.connected })
    }
    this.loadSavedImages()
    if (!this.data.debugMode && !this.onMessageBound) {
      this.registerCallbacks()
    }
  },

  onUnload() {
    this.log('页面卸载')
    this.removeCallbacks()
    app.disconnectTCP()
  },

  loadSavedImages() {
    const images = wx.getStorageSync('savedImages') || []
    this.log('加载本地图片: ' + images.length + ' 张')
    this.setData({ savedImages: images, imageCount: images.length })
  },

  connectDevice() {
    this.log('>>> 开始连接 ' + app.globalData.esp32IP + ':' + app.globalData.esp32Port)

    app.connectTCP((success) => {
      if (!success) {
        this.log('!!! 连接失败')
        this.setData({ connecting: false })
        wx.showModal({ title: '连接失败', content: '无法创建Socket', showCancel: false, complete: () => wx.navigateBack() })
      }
    })
  },

  onMessage(res) {
    const bytes = new Uint8Array(res.message)
    if (!this.data.connected) {
      const info = String.fromCharCode(...bytes).trim()
      this.log('<<< 握手响应: ' + info)
      app.setConnected(true)
      this.setData({ connected: true, connecting: false })
      return
    }
    this.onReceiveData(res.message)
  },

  onClose() {
    this.log('<<< 连接已关闭')
    this.setData({ connected: false, capturing: false })
  },

  onError(err) {
    this.log('!!! 连接错误: ' + JSON.stringify(err))
    this.setData({ connected: false, connecting: false })
    wx.showModal({ title: '连接失败', content: '无法连接设备', showCancel: false, complete: () => wx.navigateBack() })
  },

  captureImage() {
    this.log('>>> captureImage 调用, connected=' + this.data.connected + ', capturing=' + this.data.capturing)

    if (!this.data.connected) {
      this.log('!!! 未连接ESP32，无法拍照')
      wx.showToast({ title: '请先连接ESP32', icon: 'none' })
      return
    }

    if (this.data.capturing) {
      this.log('!!! 正在采集中，请等待')
      return
    }

    this.setData({ capturing: true, progress: 0 })
    this.receiveBuffer = null
    this.receiveOffset = 0
    this.expectedLength = 0
    this.chunkCount = 0
    this.headerBuffer = []

    this.log('>>> 发送CAPTURE命令')
    app.sendCommand('CAPTURE')
  },

  onReceiveData(data) {
    const bytes = new Uint8Array(data)
    let offset = 0

    while (offset < bytes.length) {
      if (!this.receiveBuffer) {
        while (this.headerBuffer.length < 4 && offset < bytes.length) {
          this.headerBuffer.push(bytes[offset++])
        }
        if (this.headerBuffer.length < 4) return

        this.expectedLength = (this.headerBuffer[0] << 24) | (this.headerBuffer[1] << 16) | (this.headerBuffer[2] << 8) | this.headerBuffer[3]
        this.headerBuffer = []
        this.receiveBuffer = new Uint8Array(this.expectedLength)
        this.receiveOffset = 0
        this.chunkCount = 0
        this.log('    帧头: 预期图像=' + this.expectedLength + ' 字节')
      }

      const remaining = bytes.length - offset
      const toWrite = Math.min(remaining, this.expectedLength - this.receiveOffset)
      this.receiveBuffer.set(bytes.subarray(offset, offset + toWrite), this.receiveOffset)
      this.receiveOffset += toWrite
      offset += toWrite
      this.chunkCount++

      const progress = Math.floor((this.receiveOffset / this.expectedLength) * 100)
      this.setData({ progress })

      if (this.receiveOffset >= this.expectedLength) {
        this.log('<<< 图像接收完成! 共' + this.chunkCount + '包, ' + this.receiveOffset + '字节')
        this.processImage(this.receiveBuffer)
        this.receiveBuffer = null
        this.receiveOffset = 0
        this.chunkCount = 0
        this.setData({ capturing: false, progress: 0 })
      }
    }
  },

  processImage(grayData) {
    this.log('>>> 处理图像, 长度=' + grayData.length)
    const width = grayData.length === 38400 ? 320 : 160
    const height = 120
    const rgbaData = new Uint8ClampedArray(width * height * 4)

    for (let i = 0; i < grayData.length; i++) {
      rgbaData[i * 4] = grayData[i]
      rgbaData[i * 4 + 1] = grayData[i]
      rgbaData[i * 4 + 2] = grayData[i]
      rgbaData[i * 4 + 3] = 255
    }

    const canvas = wx.createOffscreenCanvas({ type: '2d', width, height })
    const ctx = canvas.getContext('2d')
    const imgData = ctx.createImageData(width, height)
    imgData.data.set(rgbaData)
    ctx.putImageData(imgData, 0, 0)

    this.log('>>> Canvas绘制完成, 导出临时文件')
    wx.canvasToTempFilePath({
      canvas,
      success: (res) => {
        this.log('<<< 导出成功: ' + res.tempFilePath)
        this.setData({ imageData: res.tempFilePath })
        wx.showToast({ title: '采集成功', icon: 'success' })
      },
      fail: (err) => {
        this.log('!!! 导出失败: ' + JSON.stringify(err))
      }
    })
  },

  removeCallbacks() {
    app.removeMessageCallback(this.onMessageBound)
    app.removeCloseCallback(this.onCloseBound)
    app.removeErrorCallback(this.onErrorBound)
  },

  registerCallbacks() {
    this.onMessageBound = this.onMessage.bind(this)
    this.onCloseBound = this.onClose.bind(this)
    this.onErrorBound = this.onError.bind(this)
    app.addMessageCallback(this.onMessageBound)
    app.addCloseCallback(this.onCloseBound)
    app.addErrorCallback(this.onErrorBound)
  },

  goToAlbum() {
    this.log('>>> 打开本地相册')
    wx.navigateTo({ url: '/pages/album/album?debug=' + (this.data.debugMode ? '1' : '0') })
  },

  goToCollect() {
    this.log('>>> 跳转数据采集页面')
    wx.navigateTo({ url: '/pages/collect/collect' + (this.data.debugMode ? '?debug=1' : '') })
  },

  goToFirmware() {
    this.log('>>> 跳转固件升级页面')
    wx.navigateTo({ url: '/pages/firmware/firmware' })
  },

  goToExperiment() {
    this.log('>>> 跳转实验页面')
    wx.navigateTo({ url: '/pages/experiment/experiment' + (this.data.debugMode ? '?debug=1' : '') })
  },

  onSaveEncoderChart() {
    const chartData = app.globalData.encoderChartData
    if (!chartData || chartData.count === 0) {
      wx.showToast({ title: '无编码器数据', icon: 'none' })
      return
    }

    this.log('>>> 保存编码器图表，共' + chartData.count + '条数据')

    wx.showLoading({ title: '正在生成图表...' })

    const width = 1800
    const height = 500
    const padding = 80
    const chartWidth = width - padding * 2
    const chartHeight = height - padding * 2
    const barWidth = Math.max(chartWidth / chartData.count, 1)
    const singleBarWidth = Math.max(barWidth / 2 - 1, 1)

    const dataA = chartData.dataA
    const dataB = chartData.dataB
    const count = chartData.count
    const maxVal = Math.max(...dataA.map(Math.abs), ...dataB.map(Math.abs), 1)
    const scale = chartHeight / 2 / maxVal

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
            this.log('<<< 图表保存成功')
            app.globalData.encoderChartData = null
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
  }
})
