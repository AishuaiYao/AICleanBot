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

  // OTA 回执按行缓冲：TCP 是字节流，一条状态行可能分多个包到达，
  // 也可能多条粘在一个包里(设备侧 OTA_PROGRESS 与 OTA_ACK 常相邻)。
  _otaTextBuffer: '',
  MAX_OTA_TEXT_BUFFER: 4096,

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

    // 云开发未初始化、云函数返回结构异常、读文件抛错等任一失败路径
    // 都必须复位 downloading，否则页面会永远停在"下载中"
    const failFetch = (msg) => {
      console.error('[Firmware] ' + msg)
      this.setData({ downloading: false, status: msg, statusType: 'error' })
    }

    console.log('[Firmware] 请求云函数获取下载地址:', filename)

    const fileID = 'cloud://' + app.globalData.cloudEnvPrefix + '/firmware/' + filename

    try {
      wx.cloud.callFunction({
        name: 'getFirmwareUrl',
        // filename 为云函数首选字段，fileID 兼容只读 fileID 的旧版云函数
        data: { filename: filename, fileID: fileID },
        success: cfRes => {
          const result = cfRes && cfRes.result
          const url = result && result.url
          if (!result || !result.success || !url) {
            console.error('[Firmware] 获取下载地址失败:', result)
            failFetch('获取下载地址失败')
            return
          }

          console.log('[Firmware] 获取到下载地址:', url)
          this.setData({ status: '正在下载固件...', statusType: 'info' })

          try {
            wx.downloadFile({
              url: url,
              success: dRes => {
                if (dRes.statusCode !== 200) {
                  failFetch('下载失败: HTTP ' + dRes.statusCode)
                  return
                }
                console.log('[Firmware] 下载完成, tempFilePath:', dRes.tempFilePath)
                try {
                  const fs = wx.getFileSystemManager()
                  fs.readFile({
                    filePath: dRes.tempFilePath,
                    success: readRes => {
                      try {
                        const buffer = readRes.data
                        const size = buffer.byteLength || buffer.length
                        if (!size) {
                          failFetch('固件文件为空')
                          return
                        }
                        // readFile 可能返回带 byteOffset 的视图，不能把整个底层
                        // buffer 当成固件，否则 OTA 会多发/少发字节
                        const bytes = buffer instanceof ArrayBuffer
                          ? new Uint8Array(buffer)
                          : (buffer.buffer
                              ? new Uint8Array(buffer.buffer, buffer.byteOffset || 0, size)
                              : Uint8Array.from(buffer))
                        console.log('[Firmware] 固件大小:', size, 'bytes')
                        this._otaData = bytes
                        this._otaFilename = filename
                        const sizeStr = size > 1048576 ? (size / 1048576).toFixed(2) + ' MB' : (size / 1024).toFixed(0) + ' KB'
                        this.setData({
                          downloading: false,
                          step3Done: true,
                          otaSize: sizeStr,
                          status: '拉取成功！请切换回设备 WiFi',
                          statusType: 'success'
                        })
                      } catch (err) {
                        failFetch('解析固件失败')
                      }
                    },
                    fail: err => {
                      console.error('[Firmware] 读取文件失败:', err)
                      failFetch('读取固件失败')
                    }
                  })
                } catch (err) {
                  failFetch('读取固件失败')
                }
              },
              fail: err => {
                console.error('[Firmware] 下载失败:', err)
                failFetch('下载失败: ' + JSON.stringify(err))
              }
            })
          } catch (err) {
            failFetch('下载失败')
          }
        },
        fail: err => {
          console.error('[Firmware] 云函数调用失败:', err)
          failFetch('云函数调用失败，请检查网络')
        }
      })
    } catch (err) {
      failFetch('云开发未初始化，请检查环境配置')
    }
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
    this._otaTextBuffer = ''
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
    const bytes = new Uint8Array(res.message || new ArrayBuffer(0))
    // 分块转换，避免大包触发参数过多导致 RangeError
    let chunk = ''
    for (let i = 0; i < bytes.length; i += 8192) {
      chunk += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192))
    }

    const text = (this._otaTextBuffer || '') + chunk
    const lines = text.split('\n')
    // 末段可能只是半条状态行，留到下一个包继续拼
    this._otaTextBuffer = lines.pop() || ''
    if (this._otaTextBuffer.length > this.MAX_OTA_TEXT_BUFFER) {
      this._otaTextBuffer = this._otaTextBuffer.slice(-this.MAX_OTA_TEXT_BUFFER)
    }

    for (const line of lines) {
      const trimmed = line.trim()
      if (trimmed) this._handleOTALine(trimmed)
    }
  },

  _handleOTALine(text) {
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
