#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "esp_camera.h"
#include "driver/gpio.h"
#include "esp_http_server.h"

static const char *TAG = "CAM_SRV";

// ===========================
// WiFi AP 配置
// ===========================
#define AP_SSID     "ESP32-CAM"
#define AP_PASSWORD "12345678"
#define AP_CHANNEL  1
#define AP_MAX_CONN 4

// ===========================
// 摄像头引脚定义
// ===========================
#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  15
#define CAM_PIN_SIOD  4
#define CAM_PIN_SIOC  5

#define CAM_PIN_D7    16  // Y9
#define CAM_PIN_D6    17  // Y8
#define CAM_PIN_D5    18  // Y7
#define CAM_PIN_D4    12  // Y6
#define CAM_PIN_D3    10  // Y5
#define CAM_PIN_D2    8   // Y4
#define CAM_PIN_D1    9   // Y3
#define CAM_PIN_D0    11  // Y2

#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF  7
#define CAM_PIN_PCLK  13

// ===========================
// WiFi AP 初始化
// ===========================
static void wifi_ap_init(void)
{
    ESP_LOGI(TAG, "[WiFi] 初始化网络接口...");
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();

    ESP_LOGI(TAG, "[WiFi] 初始化WiFi驱动...");
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t wifi_config = {};
    strcpy((char *)wifi_config.ap.ssid, AP_SSID);
    strcpy((char *)wifi_config.ap.password, AP_PASSWORD);
    wifi_config.ap.ssid_len = strlen(AP_SSID);
    wifi_config.ap.channel = AP_CHANNEL;
    wifi_config.ap.max_connection = AP_MAX_CONN;
    wifi_config.ap.authmode = WIFI_AUTH_WPA_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "[WiFi] AP热点已启动");
    ESP_LOGI(TAG, "[WiFi] SSID: %s", AP_SSID);
    ESP_LOGI(TAG, "[WiFi] 密码: %s", AP_PASSWORD);
    ESP_LOGI(TAG, "[WiFi] IP: 192.168.4.1");
}

// ===========================
// 摄像头初始化
// ===========================
static void camera_init(void)
{
    ESP_LOGI(TAG, "[Camera] 初始化摄像头...");
    
    camera_config_t config = {};
    config.pin_pwdn = CAM_PIN_PWDN;
    config.pin_reset = CAM_PIN_RESET;
    config.pin_xclk = CAM_PIN_XCLK;
    config.pin_sccb_sda = CAM_PIN_SIOD;
    config.pin_sccb_scl = CAM_PIN_SIOC;

    config.pin_d7 = CAM_PIN_D7;
    config.pin_d6 = CAM_PIN_D6;
    config.pin_d5 = CAM_PIN_D5;
    config.pin_d4 = CAM_PIN_D4;
    config.pin_d3 = CAM_PIN_D3;
    config.pin_d2 = CAM_PIN_D2;
    config.pin_d1 = CAM_PIN_D1;
    config.pin_d0 = CAM_PIN_D0;

    config.pin_vsync = CAM_PIN_VSYNC;
    config.pin_href = CAM_PIN_HREF;
    config.pin_pclk = CAM_PIN_PCLK;

    config.xclk_freq_hz = 20000000;
    config.ledc_timer = LEDC_TIMER_0;
    config.ledc_channel = LEDC_CHANNEL_0;

    config.pixel_format = PIXFORMAT_GRAYSCALE;
    config.frame_size = FRAMESIZE_QQVGA;  // 160x120
    config.jpeg_quality = 0;
    config.fb_count = 1;
    config.grab_mode = CAMERA_GRAB_LATEST;
    config.fb_location = CAMERA_FB_IN_PSRAM;

    ESP_ERROR_CHECK(esp_camera_init(&config));
    ESP_LOGI(TAG, "[Camera] 初始化成功 (QQVGA 160x120 灰度)");
}

// ===========================
// HTTP 处理函数：拍照
// ===========================
static esp_err_t capture_handler(httpd_req_t *req)
{
    ESP_LOGI(TAG, "[HTTP] 收到拍照请求");

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        ESP_LOGE(TAG, "[Camera] 采集失败!");
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera capture failed");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "[Camera] 采集成功: %dx%d, 大小=%lu bytes", 
             fb->width, fb->height, (unsigned long)fb->len);

    // 设置响应头
    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "Content-Disposition", "attachment; filename=capture.bin");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    // 发送帧头：4字节大端长度
    uint32_t frame_size = fb->len;
    uint8_t header[4];
    header[0] = (frame_size >> 24) & 0xFF;
    header[1] = (frame_size >> 16) & 0xFF;
    header[2] = (frame_size >> 8) & 0xFF;
    header[3] = frame_size & 0xFF;
    httpd_resp_send_chunk(req, (char *)header, 4);

    // 发送图像数据
    httpd_resp_send_chunk(req, (char *)fb->buf, fb->len);
    httpd_resp_send_chunk(req, NULL, 0);  // 结束响应

    esp_camera_fb_return(fb);
    ESP_LOGI(TAG, "[HTTP] 图像发送完成");

    return ESP_OK;
}

// ===========================
// HTTP 处理函数：测试连接
// ===========================
static esp_err_t ping_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_send(req, "OK", 2);
    return ESP_OK;
}

// ===========================
// HTTP 服务器启动
// ===========================
static httpd_handle_t start_webserver(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.lru_purge_enable = true;

    ESP_LOGI(TAG, "[HTTP] 启动服务器，端口: %d", config.server_port);

    httpd_handle_t server = NULL;
    if (httpd_start(&server, &config) == ESP_OK) {
        // 注册URI处理程序
        httpd_uri_t capture_uri = {
            .uri       = "/capture",
            .method    = HTTP_GET,
            .handler   = capture_handler,
            .user_ctx  = NULL
        };
        httpd_register_uri_handler(server, &capture_uri);

        httpd_uri_t ping_uri = {
            .uri       = "/ping",
            .method    = HTTP_GET,
            .handler   = ping_handler,
            .user_ctx  = NULL
        };
        httpd_register_uri_handler(server, &ping_uri);

        ESP_LOGI(TAG, "[HTTP] 服务器启动成功");
        ESP_LOGI(TAG, "[HTTP] 拍照地址: http://192.168.4.1/capture");
        return server;
    }

    ESP_LOGE(TAG, "[HTTP] 服务器启动失败!");
    return NULL;
}

// ===========================
// 主函数
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP32-S3 Camera Server (HTTP Mode)");
    ESP_LOGI(TAG, "========================================");

    // 初始化NVS
    ESP_LOGI(TAG, "[系统] 初始化NVS存储...");
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "[系统] NVS需要擦除并重新初始化");
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);
    ESP_LOGI(TAG, "[系统] NVS初始化成功");

    // 初始化WiFi AP
    wifi_ap_init();

    // 初始化摄像头
    camera_init();

    // 启动HTTP服务器
    start_webserver();

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s 密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "访问: http://192.168.4.1/capture 拍照");
    ESP_LOGI(TAG, "========================================");
}
