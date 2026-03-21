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
// 端口配置
// ===========================
#define TCP_PORT     5000

static int s_client_socket = -1;
static volatile bool s_running = true;

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
// TCP 服务器任务（按需采集）
// ===========================
static void tcp_server_task(void *pvParameters)
{
    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;
    socklen_t addr_len = sizeof(client_addr);

    ESP_LOGI(TAG, "[TCP] 创建Socket...");
    int server_socket = socket(AF_INET, SOCK_STREAM, 0);
    if (server_socket < 0) {
        ESP_LOGE(TAG, "[TCP] Socket创建失败!");
        vTaskDelete(NULL);
        return;
    }
    
    int opt = 1;
    setsockopt(server_socket, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_port = htons(TCP_PORT);

    if (bind(server_socket, (struct sockaddr *)&server_addr, sizeof(server_addr)) != 0) {
        ESP_LOGE(TAG, "[TCP] 绑定端口失败!");
        close(server_socket);
        vTaskDelete(NULL);
        return;
    }

    if (listen(server_socket, 1) != 0) {
        ESP_LOGE(TAG, "[TCP] 监听失败!");
        close(server_socket);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "[TCP] 监听端口: %d (等待客户端连接)", TCP_PORT);

    while (s_running) {
        ESP_LOGI(TAG, "[TCP] 等待客户端连接...");
        s_client_socket = accept(server_socket, (struct sockaddr *)&client_addr, &addr_len);
        
        if (s_client_socket < 0) {
            ESP_LOGW(TAG, "[TCP] accept异常");
            continue;
        }

        ESP_LOGI(TAG, "[TCP] 客户端已连接: %s:%d", 
                 inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));

        char cmd_buf[32];
        while (s_running) {
            ESP_LOGI(TAG, "[TCP] 等待命令...");
            int len = recv(s_client_socket, cmd_buf, sizeof(cmd_buf) - 1, 0);
            if (len <= 0) {
                ESP_LOGI(TAG, "[TCP] 客户端断开连接");
                break;
            }
            cmd_buf[len] = '\0';

            ESP_LOGI(TAG, "[TCP] 收到命令: \"%s\"", cmd_buf);

            // 收到CAPTURE命令，采集一帧并返回
            if (strcmp(cmd_buf, "CAPTURE") == 0) {
                ESP_LOGI(TAG, "[Camera] 开始采集图像...");
                camera_fb_t *fb = esp_camera_fb_get();
                if (!fb) {
                    ESP_LOGE(TAG, "[Camera] 采集失败!");
                    continue;
                }
                ESP_LOGI(TAG, "[Camera] 采集成功: %dx%d, 大小=%lu bytes", 
                         fb->width, fb->height, (unsigned long)fb->len);

                // 发送帧头：4字节大端长度
                uint32_t frame_size = fb->len;
                uint8_t header[4];
                header[0] = (frame_size >> 24) & 0xFF;
                header[1] = (frame_size >> 16) & 0xFF;
                header[2] = (frame_size >> 8) & 0xFF;
                header[3] = frame_size & 0xFF;

                int sent_header = send(s_client_socket, header, 4, 0);
                ESP_LOGI(TAG, "[TCP] 发送帧头: %d bytes", sent_header);
                
                int sent_data = send(s_client_socket, fb->buf, fb->len, 0);
                ESP_LOGI(TAG, "[TCP] 发送图像数据: %d bytes", sent_data);
                
                esp_camera_fb_return(fb);
                ESP_LOGI(TAG, "[TCP] 图像发送完成!");
            }
        }

        close(s_client_socket);
        s_client_socket = -1;
        ESP_LOGI(TAG, "[TCP] 连接已关闭");
    }

    close(server_socket);
    ESP_LOGI(TAG, "[TCP] 服务器停止");
    vTaskDelete(NULL);
}

// ===========================
// 主函数
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP32-S3 Camera Server (AP Mode)");
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

    // 创建TCP服务器任务
    ESP_LOGI(TAG, "[系统] 启动TCP服务器...");
    xTaskCreate(tcp_server_task, "tcp_server", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s 密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "连接后访问: 192.168.4.1:5000");
    ESP_LOGI(TAG, "========================================");
}
