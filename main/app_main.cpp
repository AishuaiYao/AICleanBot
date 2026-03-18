#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netdb.h>
#include <arpa/inet.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "esp_camera.h"
#include "driver/gpio.h"

static const char *TAG = "CAM_SRV";

// ===========================
// WiFi AP 配置
// ===========================
#define AP_SSID     "CAM-AP"
#define AP_PASSWORD "*HA39&q2Iah"
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
// TCP 服务器配置
// ===========================
#define TCP_PORT     5000
#define TCP_BACKLOG  1

static int s_client_socket = -1;
static int s_server_socket = -1;
static volatile bool s_running = true;
static int s_frame_count = 0;

// ===========================
// WiFi AP 初始化
// ===========================
static void wifi_ap_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();

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

    esp_netif_ip_info_t ip_info;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
    ESP_ERROR_CHECK(esp_netif_get_ip_info(netif, &ip_info));

    ESP_LOGI(TAG, "WiFi AP started");
    ESP_LOGI(TAG, "SSID: %s", AP_SSID);
    ESP_LOGI(TAG, "Password: %s", AP_PASSWORD);
    ESP_LOGI(TAG, "IP: " IPSTR, IP2STR(&ip_info.ip));
}

// ===========================
// 摄像头初始化
// ===========================
static void camera_init(void)
{
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

    // 禁用帧缓冲区自动分配，使用PSRAM
    config.fb_location = CAMERA_FB_IN_PSRAM;

    ESP_ERROR_CHECK(esp_camera_init(&config));
    ESP_LOGI(TAG, "Camera initialized (QQVGA GRAYSCALE)");
}

// ===========================
// TCP 服务器任务
// ===========================
static void tcp_server_task(void *pvParameters)
{
    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;
    socklen_t addr_len = sizeof(client_addr);

    // 创建socket
    s_server_socket = socket(AF_INET, SOCK_STREAM, 0);
    if (s_server_socket < 0) {
        ESP_LOGE(TAG, "Failed to create socket");
        vTaskDelete(NULL);
        return;
    }

    int opt = 1;
    setsockopt(s_server_socket, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    // 绑定端口
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_port = htons(TCP_PORT);

    if (bind(s_server_socket, (struct sockaddr *)&server_addr, sizeof(server_addr)) != 0) {
        ESP_LOGE(TAG, "Socket bind failed");
        close(s_server_socket);
        vTaskDelete(NULL);
        return;
    }

    if (listen(s_server_socket, TCP_BACKLOG) != 0) {
        ESP_LOGE(TAG, "Socket listen failed");
        close(s_server_socket);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "TCP server listening on port %d", TCP_PORT);

    while (s_running) {
        ESP_LOGI(TAG, "Waiting for client connection...");

        s_client_socket = accept(s_server_socket, (struct sockaddr *)&client_addr, &addr_len);
        if (s_client_socket < 0) {
            continue;
        }

        ESP_LOGI(TAG, "Client connected: %s", inet_ntoa(client_addr.sin_addr));

        // 发送图像循环
        while (s_running) {
            camera_fb_t *fb = esp_camera_fb_get();
            if (!fb) {
                ESP_LOGE(TAG, "Camera capture failed");
                continue;
            }

            // 发送帧头: 4字节大端长度
            uint32_t frame_size = fb->len;
            uint8_t header[4];
            header[0] = (frame_size >> 24) & 0xFF;
            header[1] = (frame_size >> 16) & 0xFF;
            header[2] = (frame_size >> 8) & 0xFF;
            header[3] = frame_size & 0xFF;

            // 发送帧头
            int sent = send(s_client_socket, header, 4, 0);
            if (sent != 4) {
                ESP_LOGI(TAG, "Client disconnected");
                esp_camera_fb_return(fb);
                break;
            }

            // 发送图像数据
            sent = send(s_client_socket, fb->buf, fb->len, 0);
            esp_camera_fb_return(fb);

            if (sent != frame_size) {
                ESP_LOGI(TAG, "Client disconnected");
                break;
            }

            s_frame_count++;
            ESP_LOGI(TAG, "Frame %d sent, size: %lu bytes", s_frame_count, (unsigned long)frame_size);
        }

        close(s_client_socket);
        s_client_socket = -1;
        ESP_LOGI(TAG, "Waiting for new client...");
    }

    if (s_server_socket >= 0) {
        close(s_server_socket);
    }

    ESP_LOGI(TAG, "Server stopped, total frames sent: %d", s_frame_count);
    vTaskDelete(NULL);
}

// ===========================
// 主函数
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "ESP32-S3 Camera Server (AP Mode)");

    // 初始化NVS
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // 初始化WiFi AP
    wifi_ap_init();

    // 初始化摄像头
    camera_init();

    // 创建TCP服务器任务
    xTaskCreate(tcp_server_task, "tcp_server", 4096, NULL, 5, NULL);
}
