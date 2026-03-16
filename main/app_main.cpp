#include "esp_camera.h"
#include "esp_log.h"

static const char *TAG = "camera_app";

// 摄像头引脚配置（与Python版本一致）
#define CAM_PIN_PWDN -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK 15
#define CAM_PIN_SIOD 4
#define CAM_PIN_SIOC 5

#define CAM_PIN_D7 16
#define CAM_PIN_D6 17
#define CAM_PIN_D5 18
#define CAM_PIN_D4 12
#define CAM_PIN_D3 10
#define CAM_PIN_D2 8
#define CAM_PIN_D1 9
#define CAM_PIN_D0 11

#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF 7
#define CAM_PIN_PCLK 13

extern "C" void app_main(void)
{
    // 摄像头配置
    camera_config_t config = {
        .pin_pwdn = CAM_PIN_PWDN,
        .pin_reset = CAM_PIN_RESET,
        .pin_xclk = CAM_PIN_XCLK,
        .pin_sccb_sda = CAM_PIN_SIOD,
        .pin_sccb_scl = CAM_PIN_SIOC,

        .pin_d7 = CAM_PIN_D7,
        .pin_d6 = CAM_PIN_D6,
        .pin_d5 = CAM_PIN_D5,
        .pin_d4 = CAM_PIN_D4,
        .pin_d3 = CAM_PIN_D3,
        .pin_d2 = CAM_PIN_D2,
        .pin_d1 = CAM_PIN_D1,
        .pin_d0 = CAM_PIN_D0,

        .pin_vsync = CAM_PIN_VSYNC,
        .pin_href = CAM_PIN_HREF,
        .pin_pclk = CAM_PIN_PCLK,

        // 灰度图、QQVGA(160x120)、20MHz时钟
        .xclk_freq_hz = 20000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_GRAYSCALE,
        .frame_size = FRAMESIZE_QQVGA,
        .jpeg_quality = 10,
        .fb_count = 2,
    };

    ESP_LOGI(TAG, "初始化摄像头");

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "摄像头初始化失败: 0x%x", err);
        return;
    }

    ESP_LOGI(TAG, "摄像头初始化成功，开始采集图像");

    // 持续采集图像
    int frame_count = 0;
    while (true) {
        camera_fb_t *fb = esp_camera_fb_get();

        if (fb) {
            frame_count++;
            ESP_LOGI(TAG, "帧 %d: 大小=%d字节, 宽度=%d, 高度=%d, 格式=%d",
                     frame_count, fb->len, fb->width, fb->height, fb->format);

            esp_camera_fb_return(fb);
        } else {
            ESP_LOGW(TAG, "采集失败");
        }

        vTaskDelay(100 / portTICK_PERIOD_MS);
    }
}
