Page({
  data: {
    images: [],
    selectedCount: 0,
    uploadedCount: 0,
    storageSize: '0KB',
    uploading: false,
    uploadProgress: 0,
    uploadCurrent: 0,
    uploadTotal: 0,
    debugMode: false,
    // 云端状态
    showCloud: false,
    cloudImages: [],
    cloudLoading: false,
    cloudSelectedCount: 0,
    cloudPage: 0,
    cloudHasMore: true
  },

  onLoad(options) {
    const debugMode = options.debug === '1'
    this.setData({ debugMode })
    this.loadImages()
  },

  onShow() {
    // 保存当前选中的路径
    const selectedPaths = this.data.images
      .filter(img => img.selected)
      .map(img => img.path)
    
    this.loadImages(selectedPaths)
  },

  loadImages(selectedPaths = []) {
    let images = wx.getStorageSync('savedImages') || []
    
    if (this.data.debugMode && images.length === 0) {
      this.generateTestImages()
      return
    }

    const processedImages = images.map(img => ({
      ...img,
      selected: selectedPaths.includes(img.path)
    }))
    const uploadedCount = images.filter(img => img.uploaded).length
    const selectedCount = processedImages.filter(img => img.selected).length

    this.setData({
      images: processedImages,
      selectedCount,
      uploadedCount,
      storageSize: images.length > 0 ? '计算中...' : '0KB'
    })

    if (images.length > 0) {
      this.calculateStorageSize(images)
    }
  },

  generateTestImages() {
    this.setData({ storageSize: '生成测试数据...' })

    const testImages = []
    const width = 160
    const height = 120

    for (let i = 0; i < 6; i++) {
      const canvas = wx.createOffscreenCanvas({ type: '2d', width, height })
      const ctx = canvas.getContext('2d')
      const imgData = ctx.createImageData(width, height)

      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const idx = (y * width + x) * 4
          let gray = 0

          if (i === 0) gray = (x + y) % 256
          else if (i === 1) gray = Math.sin(x / 10) * 127 + 128
          else if (i === 2) gray = ((x % 20) < 10) ? 255 : 0
          else if (i === 3) gray = ((y % 20) < 10) ? 255 : 0
          else if (i === 4) gray = Math.sqrt((x-80)**2 + (y-60)**2) * 2
          else gray = Math.random() * 256

          imgData.data[idx] = gray
          imgData.data[idx + 1] = gray
          imgData.data[idx + 2] = gray
          imgData.data[idx + 3] = 255
        }
      }

      ctx.putImageData(imgData, 0, 0)

      wx.canvasToTempFilePath({
        canvas,
        success: (res) => {
          wx.saveFile({
            tempFilePath: res.tempFilePath,
            success: (saveRes) => {
              testImages.push({
                path: saveRes.savedFilePath,
                time: new Date().toLocaleString(),
                uploaded: Math.random() > 0.5
              })

              if (testImages.length === 6) {
                wx.setStorageSync('savedImages', testImages)
                this.loadImages()
              }
            }
          })
        }
      })
    }
  },

  calculateStorageSize(images) {
    let totalSize = 0
    let count = 0

    images.forEach(img => {
      wx.getFileInfo({
        filePath: img.path,
        success: (res) => {
          totalSize += res.size
          count++
          this.updateStorageSize(totalSize, count, images.length)
        },
        fail: () => {
          count++
          this.updateStorageSize(totalSize, count, images.length)
        }
      })
    })

    if (images.length === 0) {
      this.setData({ storageSize: '0KB' })
    }
  },

  updateStorageSize(totalSize, count, total) {
    if (count === total) {
      let sizeText = ''
      if (totalSize < 1024) {
        sizeText = totalSize + 'B'
      } else if (totalSize < 1024 * 1024) {
        sizeText = (totalSize / 1024).toFixed(1) + 'KB'
      } else {
        sizeText = (totalSize / 1024 / 1024).toFixed(2) + 'MB'
      }
      this.setData({ storageSize: sizeText })
    }
  },

  // 本地图片操作
  toggleSelect(e) {
    const index = e.currentTarget.dataset.index
    const images = this.data.images
    images[index].selected = !images[index].selected
    const selectedCount = images.filter(img => img.selected).length
    this.setData({ images, selectedCount })
  },

  previewImage(e) {
    const index = e.currentTarget.dataset.index
    const urls = this.data.images.map(img => img.path)
    wx.previewImage({
      current: this.data.images[index].path,
      urls: urls
    })
  },

  selectAll() {
    const images = this.data.images.map(img => ({ ...img, selected: true }))
    this.setData({ images, selectedCount: images.length })
  },

  deselectAll() {
    const images = this.data.images.map(img => ({ ...img, selected: false }))
    this.setData({ images, selectedCount: 0 })
  },

  deleteSelected() {
    if (this.data.selectedCount === 0) {
      wx.showToast({ title: '请先选择图片', icon: 'none' })
      return
    }

    wx.showModal({
      title: '确认删除',
      content: `确定删除 ${this.data.selectedCount} 张图片？`,
      success: (res) => {
        if (res.confirm) {
          const selectedPaths = this.data.images
            .filter(img => img.selected)
            .map(img => img.path)

          selectedPaths.forEach(path => {
            try {
              wx.removeSavedFile({ filePath: path })
            } catch (e) {}
          })

          let images = this.data.images.filter(img => !img.selected)
          const storageImages = images.map(({ selected, ...rest }) => rest)
          wx.setStorageSync('savedImages', storageImages)

          const uploadedCount = images.filter(img => img.uploaded).length

          this.setData({
            images,
            selectedCount: 0,
            uploadedCount,
            storageSize: '计算中...'
          })

          this.calculateStorageSize(storageImages)
          wx.showToast({ title: '删除成功', icon: 'success' })
        }
      }
    })
  },

  uploadSelected() {
    if (this.data.selectedCount === 0) {
      wx.showToast({ title: '请先选择图片', icon: 'none' })
      return
    }
    this.checkNetworkAndUpload()
  },

  checkNetworkAndUpload() {
    wx.getNetworkType({
      success: (res) => {
        if (res.networkType !== 'wifi') {
          wx.showModal({
            title: '网络提示',
            content: '当前非WiFi环境，建议切换到家庭WiFi后上传，是否继续？',
            success: (modalRes) => {
              if (modalRes.confirm) {
                this.startUpload()
              }
            }
          })
          return
        }

        wx.request({
          url: 'https://www.baidu.com',
          method: 'HEAD',
          timeout: 3000,
          success: () => {
            this.startUpload()
          },
          fail: () => {
            wx.showModal({
              title: '网络提示',
              content: '当前WiFi无法访问互联网，请切换到家庭WiFi后再上传',
              showCancel: false
            })
          }
        })
      }
    })
  },

  startUpload() {
    const selectedImages = this.data.images.filter(img => img.selected)
    this.setData({
      uploading: true,
      uploadProgress: 0,
      uploadCurrent: 0,
      uploadTotal: selectedImages.length
    })

    let successCount = 0
    let failCount = 0
    let completed = 0
    const db = wx.cloud.database()

    selectedImages.forEach((img) => {
      wx.getFileSystemManager().readFile({
        filePath: img.path,
        encoding: 'base64',
        success: (res) => {
          db.collection('dataset').add({
            data: {
              image: res.data,
              width: 160,
              height: 120,
              time: new Date(),
              uploadedAt: db.serverDate()
            },
            success: () => {
              successCount++
              const images = this.data.images
              const idx = images.findIndex(item => item.path === img.path)
              if (idx !== -1) {
                images[idx].uploaded = true
                images[idx].selected = false
              }
              this.setData({ images })
            },
            fail: (err) => {
              failCount++
              console.log('上传失败:', err)
            },
            complete: () => {
              completed++
              this.setData({
                uploadProgress: Math.round((completed / selectedImages.length) * 100),
                uploadCurrent: completed
              })

              if (completed === selectedImages.length) {
                const storageImages = this.data.images.map(({ selected, ...rest }) => rest)
                wx.setStorageSync('savedImages', storageImages)
                const uploadedCount = this.data.images.filter(img => img.uploaded).length

                this.setData({
                  uploading: false,
                  uploadProgress: 0,
                  selectedCount: 0,
                  uploadedCount
                })

                wx.showModal({
                  title: '上传完成',
                  content: `成功: ${successCount} 张\n失败: ${failCount} 张`,
                  showCancel: false
                })
              }
            }
          })
        },
        fail: (err) => {
          failCount++
          completed++
          console.log('读取图片失败:', err)
          this.setData({
            uploadProgress: Math.round((completed / selectedImages.length) * 100),
            uploadCurrent: completed
          })
        }
      })
    })
  },

  // 云端功能
  openCloud() {
    // 显示加载状态
    this.setData({ showCloud: true, cloudLoading: true, cloudImages: [], cloudSelectedCount: 0, cloudPage: 0, cloudHasMore: true })

    // 直接尝试加载云端数据
    this.loadCloudImages()
  },

  closeCloud() {
    this.setData({ showCloud: false })
  },

  preventBubble() {
    // 阻止事件冒泡，不做任何操作
  },

  loadCloudImages() {
    const db = wx.cloud.database()
    const pageSize = 20
    const page = this.data.cloudPage

    db.collection('dataset')
      .orderBy('uploadedAt', 'desc')
      .skip(page * pageSize)
      .limit(pageSize)
      .get({
        success: (res) => {
          const newImages = res.data.map(item => ({
            _id: item._id,
            image: 'data:image/png;base64,' + item.image,
            time: item.time || item.uploadedAt,
            width: item.width || 160,
            height: item.height || 120,
            selected: false
          }))

          const cloudImages = this.data.cloudImages.concat(newImages)
          const hasMore = res.data.length === pageSize

          this.setData({
            cloudImages,
            cloudLoading: false,
            cloudSelectedCount: 0,
            cloudHasMore: hasMore,
            cloudPage: page + 1
          })
        },
        fail: (err) => {
          console.log('加载云端图片失败:', err)
          this.setData({ showCloud: false, cloudLoading: false })

          // 根据错误判断是否网络问题
          const errMsg = err.errMsg || ''
          if (errMsg.includes('timeout') || errMsg.includes('network') || errMsg.includes('request:fail')) {
            wx.showModal({
              title: '网络提示',
              content: '当前网络无法访问云端，请检查是否连接到家庭WiFi或移动数据网络',
              showCancel: false
            })
          } else {
            wx.showToast({ title: '加载失败', icon: 'none' })
          }
        }
      })
  },

  // 云端图片选择
  toggleCloudSelect(e) {
    const index = e.currentTarget.dataset.index
    const cloudImages = this.data.cloudImages
    cloudImages[index].selected = !cloudImages[index].selected
    const cloudSelectedCount = cloudImages.filter(img => img.selected).length
    this.setData({ cloudImages, cloudSelectedCount })
  },

  selectAllCloud() {
    const cloudImages = this.data.cloudImages.map(img => ({ ...img, selected: true }))
    this.setData({ cloudImages, cloudSelectedCount: cloudImages.length })
  },

  deselectAllCloud() {
    const cloudImages = this.data.cloudImages.map(img => ({ ...img, selected: false }))
    this.setData({ cloudImages, cloudSelectedCount: 0 })
  },

  previewCloudImage(e) {
    const index = e.currentTarget.dataset.index
    const urls = this.data.cloudImages.map(img => img.image)
    wx.previewImage({
      current: this.data.cloudImages[index].image,
      urls: urls
    })
  },

  // 批量删除云端图片
  deleteCloudSelected() {
    if (this.data.cloudSelectedCount === 0) {
      wx.showToast({ title: '请先选择图片', icon: 'none' })
      return
    }

    wx.showModal({
      title: '确认删除',
      content: `确定从云端删除 ${this.data.cloudSelectedCount} 张图片？`,
      success: (res) => {
        if (res.confirm) {
          const selectedImages = this.data.cloudImages.filter(img => img.selected)
          let successCount = 0
          let failCount = 0
          const total = selectedImages.length
          const db = wx.cloud.database()

          wx.showLoading({ title: '删除中...', mask: true })

          selectedImages.forEach((img) => {
            db.collection('dataset').doc(img._id).remove({
              success: () => {
                successCount++
                if (successCount + failCount === total) {
                  wx.hideLoading()
                  if (failCount > 0) {
                    wx.showModal({
                      title: '删除完成',
                      content: `成功: ${successCount} 张\n失败: ${failCount} 张\n\n失败可能原因：数据库权限不足，请在云开发控制台设置 dataset 集合权限为"所有用户可读写"`,
                      showCancel: false
                    })
                  } else {
                    wx.showToast({ title: '删除成功', icon: 'success' })
                  }
                  // 从列表中移除已删除的图片
                  const cloudImages = this.data.cloudImages.filter(item => !item.selected)
                  this.setData({ cloudImages, cloudSelectedCount: 0 })
                }
              },
              fail: (err) => {
                console.log('删除失败:', err)
                failCount++
                if (successCount + failCount === total) {
                  wx.hideLoading()
                  wx.showModal({
                    title: '删除完成',
                    content: `成功: ${successCount} 张\n失败: ${failCount} 张\n\n失败可能原因：数据库权限不足，请在云开发控制台设置 dataset 集合权限为"所有用户可读写"`,
                    showCancel: false
                  })
                  // 只移除成功删除的图片
                  const deletedIds = selectedImages.slice(0, successCount).map(i => i._id)
                  const cloudImages = this.data.cloudImages.filter(item => !deletedIds.includes(item._id))
                  this.setData({ cloudImages, cloudSelectedCount: 0 })
                }
              }
            })
          })
        }
      }
    })
  },

  // 批量保存到相册
  saveCloudSelected() {
    if (this.data.cloudSelectedCount === 0) {
      wx.showToast({ title: '请先选择图片', icon: 'none' })
      return
    }

    const selectedImages = this.data.cloudImages.filter(img => img.selected)
    let savedCount = 0
    let failCount = 0
    const total = selectedImages.length

    wx.showLoading({ title: '保存中...', mask: true })

    selectedImages.forEach((img, index) => {
      const base64 = img.image.split(',')[1]
      const fs = wx.getFileSystemManager()
      const filePath = wx.env.USER_DATA_PATH + '/cloud_' + Date.now() + '_' + index + '.png'
      
      fs.writeFile({
        filePath: filePath,
        data: base64,
        encoding: 'base64',
        success: () => {
          wx.saveImageToPhotosAlbum({
            filePath: filePath,
            success: () => {
              savedCount++
              fs.unlinkSync(filePath)
              this.checkSaveComplete(savedCount, failCount, total)
            },
            fail: (err) => {
              failCount++
              fs.unlinkSync(filePath)
              this.checkSaveComplete(savedCount, failCount, total)
            }
          })
        },
        fail: () => {
          failCount++
          this.checkSaveComplete(savedCount, failCount, total)
        }
      })
    })
  },

  checkSaveComplete(savedCount, failCount, total) {
    if (savedCount + failCount === total) {
      wx.hideLoading()
      wx.showModal({
        title: '保存完成',
        content: `成功: ${savedCount} 张\n失败: ${failCount} 张`,
        showCancel: false
      })
      
      // 清除选择状态
      const cloudImages = this.data.cloudImages.map(img => ({ ...img, selected: false }))
      this.setData({ cloudImages, cloudSelectedCount: 0 })
    }
  }
})
