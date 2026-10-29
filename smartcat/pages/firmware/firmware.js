const app = getApp()

// OTA 发送参数：每片 2KB，每个窗口 8 片(16KB) 等一次设备 ACK
const OTA_CHUNK_SIZE = 2048
const OTA_WINDOW_CHUNKS = 8

Page({
  data: {
    firmwareList: [],
    selectedIndex: -1,
    selectedName: '',
    otaSize: '',
    step1Done: false,
    step2Done: false,
    step3Done: false,
    step4Done: false,
    step5Done: false,
    downloading: false,
    flashing: false,
    progress: 0,
    status: '',
    statusType: ''
  },

  onLoad() {
    this.loadFirmwareList()
  },

  onUnload() {
    this._clearOTATimeout()
    app.clearOTACallback()
  },

  loadFirmwareList() {
    const list = require('../../firmware-config.js')
    this.setData({ firmwareList: list })
  },

  // Step 1: 选择固件
  onPickerChange(e) {
    const idx = e.detail.value
    const name = this.data.firmwareList[idx]
    this.setData({
      selectedIndex: idx,
      selectedName: name,
      step1Done: true
    })
  },

  // Step 2: 确认切换到家庭WiFi
  confirmStep2() {
    this.setData({ step2Done: true, status: '', statusType: '' })
  },

  // Step 3: 拉取固件到本地
  startFetch() {
    const filename = this.data.firmwareList[this.data.selectedIndex]
    if (!filename) return

    this.setData({ downloading: true, status: '正在获取下载地址...', statusType: 'info' })

    console.log('[Firmware] 请求云函数获取下载地址:', filename)

    const fileID = 'cloud://' + app.globalData.cloudEnvPrefix + '/firmware/' + filename

    wx.cloud.callFunction({
      name: 'getFirmwareUrl',
      // filename 为云函数首选字段，fileID 兼容只读 fileID 的旧版云函数
      data: { filename: filename, fileID: fileID },
      success: cfRes => {
        const { success, url } = cfRes.result
        if (!success || !url) {
          console.error('[Firmware] 获取下载地址失败:', cfRes.result)
          this.setData({ downloading: false, status: '获取下载地址失败', statusType: 'error' })
          return
        }

        console.log('[Firmware] 获取到下载地址:', url)
        this.setData({ status: '正在下载固件...', statusType: 'info' })

        wx.downloadFile({
          url: url,
          success: dRes => {
            if (dRes.statusCode !== 200) {
              console.error('[Firmware] HTTP 状态码异常:', dRes.statusCode)
              this.setData({ downloading: false, status: '下载失败: HTTP ' + dRes.statusCode, statusType: 'error' })
              return
            }
            console.log('[Firmware] 下载完成, tempFilePath:', dRes.tempFilePath)
            const fs = wx.getFileSystemManager()
            fs.readFile({
              filePath: dRes.tempFilePath,
              success: readRes => {
                const buffer = readRes.data
                const size = buffer.byteLength || buffer.length
                console.log('[Firmware] 固件大小:', size, 'bytes')
                this._otaData = new Uint8Array(buffer instanceof ArrayBuffer ? buffer : buffer.buffer)
                this._otaFilename = filename
                const sizeStr = size > 1048576 ? (size / 1048576).toFixed(2) + ' MB' : (size / 1024).toFixed(0) + ' KB'
                this.setData({
                  downloading: false,
                  step3Done: true,
                  otaSize: sizeStr,
                  status: '拉取成功！请切换回设备 WiFi',
                  statusType: 'success'
                })
              },
              fail: err => {
                console.error('[Firmware] 读取文件失败:', err)
                this.setData({ downloading: false, status: '读取固件失败', statusType: 'error' })
              }
            })
          },
          fail: err => {
            console.error('[Firmware] 下载失败:', err)
            this.setData({ downloading: false, status: '下载失败: ' + JSON.stringify(err), statusType: 'error' })
          }
        })
      },
      fail: err => {
        console.error('[Firmware] 云函数调用失败:', err)
        this.setData({ downloading: false, status: '云函数调用失败，请检查网络', statusType: 'error' })
      }
    })
  },

  // Step 4: 确认切换回设备WiFi
  confirmStep4() {
    this.setData({ step4Done: true, status: '已就绪，请确保设备页面已连接 LinePatrol V1', statusType: 'info' })
  },

  // Step 5: 烧录固件
  startFlash() {
    if (!this._otaData || !this._otaFilename) {
      this.setData({ status: '请先拉取固件', statusType: 'error' })
      return
    }
    if (this.data.flashing) return

    this.setData({ flashing: true, progress: 0, status: '正在启动 OTA...', statusType: 'info' })

    app.setOTACallback(this.onOTAMessage.bind(this))
    this._otaOffset = 0
    this._otaAckTotal = 0
    this._otaState = 'wait_ready'

    this._armOTATimeout(10000, '设备未返回 OTA_READY')
    app.sendCommand('OTA:START:' + this._otaFilename + ':' + this._otaData.length)
  },

  // 超时守卫：任一阶段卡住都能退出，不会永久停在 flashing
  _armOTATimeout(ms, reason) {
    this._clearOTATimeout()
    this._otaTimer = setTimeout(() => {
      console.error('[Firmware] OTA 超时:', reason)
      this._failOTA(reason)
    }, ms)
  },

  _clearOTATimeout() {
    if (this._otaTimer) {
      clearTimeout(this._otaTimer)
      this._otaTimer = null
    }
  },

  _failOTA(reason) {
    this._clearOTATimeout()
    this._otaState = 'idle'
    app.clearOTACallback()
    this.setData({ flashing: false, status: '烧录失败: ' + reason + '，可重试', statusType: 'error' })
  },

  onOTAMessage(res) {
    const bytes = new Uint8Array(res.message)
    const text = String.fromCharCode.apply(null, bytes).trim()
    console.log('[Firmware] OTA 响应:', text)

    if (text.startsWith('OTA_PROGRESS:')) {
      const pct = parseInt(text.split(':')[1], 10) || 0
      const localPct = Math.floor(this._otaOffset * 100 / this._otaData.length)
      // 设备侧进度为准，但不超过本地已发送量，避免进度条回退
      this.setData({ progress: Math.min(pct, localPct) })
      return
    }

    if (this._otaState === 'wait_ready' && text === 'OTA_READY') {
      this._clearOTATimeout()
      this.setData({ status: '正在烧录固件...', statusType: 'info' })
      this._sendWindow()
      return
    }

    if (this._otaState === 'wait_ack' && text.startsWith('OTA_ACK:')) {
      const ackTotal = parseInt(text.split(':')[1], 10)
      if (isNaN(ackTotal)) return
      this._otaAckTotal = ackTotal
      if (ackTotal > this._otaOffset) {
        this._failOTA('设备确认字节数异常')
        return
      }
      this._clearOTATimeout()
      this._sendWindow()
      return
    }

    if (text === 'OTA_OK') {
      // 设备收满且写入校验通过才会回 OTA_OK
      if (this._otaOffset < this._otaData.length) {
        this._failOTA('固件未发完却收到完成确认')
        return
      }
      this._clearOTATimeout()
      this._otaState = 'idle'
      app.clearOTACallback()
      this.setData({
        flashing: false,
        progress: 100,
        step5Done: true,
        status: '烧录成功！请重启机器人，并重新打开小程序',
        statusType: 'success'
      })
      return
    }

    if (text.startsWith('OTA_FAIL:')) {
      this._failOTA(text.substring(9))
    }
  },

  // 每发满一个窗口(16KB)就等设备 ACK，不再盲发
  _sendWindow() {
    const total = this._otaData.length
    for (let i = 0; i < OTA_WINDOW_CHUNKS && this._otaOffset < total; i++) {
      const end = Math.min(this._otaOffset + OTA_CHUNK_SIZE, total)
      const chunk = this._otaData.slice(this._otaOffset, end)
      const buf = new ArrayBuffer(chunk.length)
      new Uint8Array(buf).set(chunk)
      app.sendBinary(buf)
      this._otaOffset = end
    }

    this.setData({ progress: Math.floor(this._otaOffset * 100 / total) })

    if (this._otaOffset >= total) {
      // 发完了，等设备完成写入 + 设置启动分区（Flash 写入较慢，超时放宽）
      this._otaState = 'wait_done'
      this._armOTATimeout(30000, '设备未返回烧录结果')
    } else {
      this._otaState = 'wait_ack'
      this._armOTATimeout(10000, '设备未确认已接收数据')
    }
  },

  goBack() {
    wx.navigateBack()
  }
})
