#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_camera.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "lwip/ip_addr.h"
#include "lwip/sockets.h"

static const char *TAG = "CAM_TCP";

// ===========================
// 摄像头引脚定义
// ===========================
#define CAM_PIN_PWDN  -1
#define CAM_PIN_RESET -1
#define CAM_PIN_XCLK  15
#define CAM_PIN_SIOD  4
#define CAM_PIN_SIOC  5

#define CAM_PIN_D7    16
#define CAM_PIN_D6    17
#define CAM_PIN_D5    18
#define CAM_PIN_D4    12
#define CAM_PIN_D3    10
#define CAM_PIN_D2    8
#define CAM_PIN_D1    9
#define CAM_PIN_D0    11

#define CAM_PIN_VSYNC 6
#define CAM_PIN_HREF  7
#define CAM_PIN_PCLK  13

// ===========================
// WiFi AP 配置
// ===========================
#define AP_SSID      "ESP32-CAM"
#define AP_PASSWORD  "12345678"
#define AP_CHANNEL   1
#define AP_MAX_CONN  1

// TCP Server (微信小程序禁用: <1024, 8000-8100, 6000, 8888, 8443等)
#define TCP_PORT     5000

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
// WiFi AP 初始化
// ===========================
static void wifi_init_ap(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t wifi_config = {};
    strncpy((char *)wifi_config.ap.ssid, AP_SSID, sizeof(wifi_config.ap.ssid) - 1);
    strncpy((char *)wifi_config.ap.password, AP_PASSWORD, sizeof(wifi_config.ap.password) - 1);
    wifi_config.ap.channel = AP_CHANNEL;
    wifi_config.ap.max_connection = AP_MAX_CONN;
    wifi_config.ap.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "[WiFi] AP已启动 SSID=%s 密码=%s IP=192.168.4.1", AP_SSID, AP_PASSWORD);
}

// ===========================
// 处理客户端连接
// ===========================
static void handle_client(int client_sock)
{
    ESP_LOGI(TAG, "[TCP] 客户端已连接");

    char buf[64];

    while (1) {
        int len = recv(client_sock, buf, sizeof(buf) - 1, 0);
        if (len <= 0) {
            ESP_LOGI(TAG, "[TCP] 客户端断开");
            break;
        }
        buf[len] = '\0';

        ESP_LOGI(TAG, "[TCP] 收到命令: %s", buf);

        if (strncmp(buf, "CAPTURE", 7) == 0) {
            camera_fb_t *fb = esp_camera_fb_get();
            if (!fb) {
                ESP_LOGE(TAG, "[Camera] 采集失败!");
                const char *err = "ERROR\n";
                send(client_sock, err, strlen(err), 0);
                continue;
            }

            ESP_LOGI(TAG, "[Camera] 采集成功: %dx%d, 大小=%lu bytes",
                     fb->width, fb->height, (unsigned long)fb->len);

            // 发送4字节帧头（大端长度）
            uint8_t header[4];
            uint32_t frame_size = fb->len;
            header[0] = (frame_size >> 24) & 0xFF;
            header[1] = (frame_size >> 16) & 0xFF;
            header[2] = (frame_size >> 8) & 0xFF;
            header[3] = frame_size & 0xFF;

            send(client_sock, header, 4, 0);

            // 分块发送图像数据
            uint32_t offset = 0;
            while (offset < fb->len) {
                int chunk = fb->len - offset;
                if (chunk > 1460) chunk = 1460;
                int sent = send(client_sock, fb->buf + offset, chunk, 0);
                if (sent < 0) {
                    ESP_LOGE(TAG, "[TCP] 发送失败");
                    break;
                }
                offset += sent;
            }

            ESP_LOGI(TAG, "[TCP] 图像发送完成, 共%lu bytes", (unsigned long)offset);
            esp_camera_fb_return(fb);
        }
    }

    close(client_sock);
}

// ===========================
// TCP Server 任务
// ===========================
static void tcp_server_task(void *pvParameters)
{
    int server_sock = socket(AF_INET, SOCK_STREAM, 0);

    int opt = 1;
    setsockopt(server_sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_port = htons(TCP_PORT);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    bind(server_sock, (struct sockaddr *)&addr, sizeof(addr));
    listen(server_sock, 1);

    ESP_LOGI(TAG, "[TCP] Server已启动, 端口=%d", TCP_PORT);

    while (1) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);
        int client_sock = accept(server_sock, (struct sockaddr *)&client_addr, &addr_len);

        if (client_sock >= 0) {
            handle_client(client_sock);
        }
    }

    close(server_sock);
    vTaskDelete(NULL);
}

// ===========================
// 主函数
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP32 Camera Server (WiFi AP + TCP)");
    ESP_LOGI(TAG, "========================================");

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    camera_init();
    wifi_init_ap();

    xTaskCreate(tcp_server_task, "tcp_server", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s  密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "TCP端口: %d", TCP_PORT);
    ESP_LOGI(TAG, "========================================");
}
