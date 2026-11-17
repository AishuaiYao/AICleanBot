const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

// 云存储文件路径前缀
// 仓库中为占位符 **，请改成你自己的：cloud://<云环境ID>.<bucket>/firmware/
const CLOUD_PREFIX = '**'

// 从 cloud://xxx/firmware/a.bin 里取出纯文件名，兼容只传 fileID 的调用方
function extractFilename(fileID) {
  const raw = String(fileID || '').split('?')[0]
  const idx = raw.lastIndexOf('/')
  return idx >= 0 ? raw.substring(idx + 1) : raw
}

exports.main = async (event, context) => {
  // 兼容两种入参：{ filename } 或 { fileID }
  let filename = event && event.filename
  if (!filename && event && event.fileID) {
    filename = extractFilename(event.fileID)
    console.log('[getFirmwareUrl] 由 fileID 推导出文件名:', filename)
  }
  console.log('[getFirmwareUrl] 请求文件名:', filename)

  // 只允许纯文件名，防止路径穿越（../、子目录）
  if (!filename || /[\\/]/.test(filename) || filename === '.' || filename === '..') {
    return { success: false, errMsg: 'filename 非法，只允许 /firmware/ 下的纯文件名' }
  }

  const fileID = CLOUD_PREFIX + filename
  console.log('[getFirmwareUrl] fileID:', fileID)

  let result
  try {
    result = await cloud.getTempFileURL({
      fileList: [fileID]
    })
  } catch (err) {
    console.error('[getFirmwareUrl] getTempFileURL 异常:', err)
    return {
      success: false,
      errMsg: '获取下载链接异常: ' + ((err && err.errMsg) || err)
    }
  }

  // fileList 为空或结果结构异常时直接取 [0] 会抛 TypeError，变成云函数 500；
  // 统一降级成空对象，让调用方拿到结构化的失败响应
  const file = (result && Array.isArray(result.fileList) && result.fileList[0]) || {}
  console.log('[getFirmwareUrl] 结果:', JSON.stringify(file))

  if (file.tempFileURL) {
    return {
      success: true,
      url: file.tempFileURL
    }
  } else {
    return {
      success: false,
      errMsg: file.errMsg || '获取下载链接失败'
    }
  }
}

