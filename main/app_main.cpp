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
// WiFi Station 配置（连接手机热点）
// ===========================
#define STA_SSID     "aishuai"
#define STA_PASSWORD "18611125233"

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
#define UDP_PORT     12345
#define TCP_PORT     5000

static int s_client_socket = -1;
static volatile bool s_running = true;

// ===========================
// WiFi事件处理
// ===========================
static void wifi_event_handler(void* arg, esp_event_base_t event_base,
                               int32_t event_id, void* event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "[WiFi] STA启动，开始连接...");
        esp_wifi_connect();
    } 
    else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "[WiFi] 连接失败，5秒后重试...");
        vTaskDelay(pdMS_TO_TICKS(5000));
        esp_wifi_connect();
    }
    else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "[WiFi] 连接成功!");
        ESP_LOGI(TAG, "[WiFi] IP地址: " IPSTR, IP2STR(&event->ip_info.ip));
        ESP_LOGI(TAG, "[WiFi] 网关: " IPSTR, IP2STR(&event->ip_info.gw));
        ESP_LOGI(TAG, "[WiFi] 子网掩码: " IPSTR, IP2STR(&event->ip_info.netmask));
    }
}

// ===========================
// WiFi Station 初始化
// ===========================
static void wifi_sta_init(void)
{
    ESP_LOGI(TAG, "[WiFi] 初始化网络接口...");
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    ESP_LOGI(TAG, "[WiFi] 初始化WiFi驱动...");
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    // 注册事件处理
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_config_t wifi_config = {};
    strcpy((char *)wifi_config.sta.ssid, STA_SSID);
    strcpy((char *)wifi_config.sta.password, STA_PASSWORD);

    ESP_LOGI(TAG, "[WiFi] 目标SSID: %s", STA_SSID);
    
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "[WiFi] WiFi启动完成，等待连接...");
}

// ===========================
// 获取本机IP
// ===========================
static char* get_local_ip(void)
{
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_ip_info_t ip_info;
    ESP_ERROR_CHECK(esp_netif_get_ip_info(netif, &ip_info));
    static char ip_str[16];
    sprintf(ip_str, IPSTR, IP2STR(&ip_info.ip));
    return ip_str;
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
    config.fb_location = CAMERA_FB_IN_PSRAM;

    ESP_ERROR_CHECK(esp_camera_init(&config));
    ESP_LOGI(TAG, "Camera initialized (QQVGA GRAYSCALE)");
}

// ===========================
// UDP 发现服务任务
// ===========================
static void udp_discovery_task(void *pvParameters)
{
    ESP_LOGI(TAG, "[UDP] 创建UDP Socket...");
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        ESP_LOGE(TAG, "[UDP] Socket创建失败!");
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "[UDP] Socket创建成功, fd=%d", sock);
    
    int broadcast = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcast, sizeof(broadcast));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(UDP_PORT);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGE(TAG, "[UDP] 绑定端口 %d 失败!", UDP_PORT);
        close(sock);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "[UDP] 监听端口: %d (等待发现请求)", UDP_PORT);

    char rx_buf[128];
    struct sockaddr_in client_addr;
    socklen_t addr_len = sizeof(client_addr);

    while (s_running) {
        int len = recvfrom(sock, rx_buf, sizeof(rx_buf) - 1, 0,
                          (struct sockaddr *)&client_addr, &addr_len);
        if (len > 0) {
            rx_buf[len] = '\0';
            ESP_LOGI(TAG, "[UDP] 收到消息: \"%s\" 来自 %s", rx_buf, inet_ntoa(client_addr.sin_addr));

            // 收到发现请求，回复IP
            if (strcmp(rx_buf, "DISCOVER_ESP32") == 0) {
                char response[64];
                sprintf(response, "ESP32_CAM:%s", get_local_ip());
                sendto(sock, response, strlen(response), 0,
                      (struct sockaddr *)&client_addr, addr_len);
                ESP_LOGI(TAG, "[UDP] 已回复: \"%s\"", response);
            }
        }
    }

    ESP_LOGI(TAG, "[UDP] 服务停止");
    close(sock);
    vTaskDelete(NULL);
}

// ===========================
// TCP 服务器任务（按需采集）
// ===========================
static void tcp_server_task(void *pvParameters)
{
    struct sockaddr_in server_addr;
    struct sockaddr_in client_addr;
    socklen_t addr_len = sizeof(client_addr);

    int server_socket = socket(AF_INET, SOCK_STREAM, 0);
    
    int opt = 1;
    setsockopt(server_socket, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_port = htons(TCP_PORT);

    bind(server_socket, (struct sockaddr *)&server_addr, sizeof(server_addr));
    listen(server_socket, 1);

    ESP_LOGI(TAG, "TCP server listening on port %d", TCP_PORT);

    while (s_running) {
        ESP_LOGI(TAG, "Waiting for client...");
        s_client_socket = accept(server_socket, (struct sockaddr *)&client_addr, &addr_len);
        
        if (s_client_socket < 0) continue;

        ESP_LOGI(TAG, "Client connected: %s", inet_ntoa(client_addr.sin_addr));

        char cmd_buf[32];
        while (s_running) {
            int len = recv(s_client_socket, cmd_buf, sizeof(cmd_buf) - 1, 0);
            if (len <= 0) {
                ESP_LOGI(TAG, "Client disconnected");
                break;
            }
            cmd_buf[len] = '\0';

            ESP_LOGI(TAG, "Command received: %s", cmd_buf);

            // 收到CAPTURE命令，采集一帧并返回
            if (strcmp(cmd_buf, "CAPTURE") == 0) {
                camera_fb_t *fb = esp_camera_fb_get();
                if (!fb) {
                    ESP_LOGE(TAG, "Camera capture failed");
                    continue;
                }

                // 发送帧头：4字节大端长度
                uint32_t frame_size = fb->len;
                uint8_t header[4];
                header[0] = (frame_size >> 24) & 0xFF;
                header[1] = (frame_size >> 16) & 0xFF;
                header[2] = (frame_size >> 8) & 0xFF;
                header[3] = frame_size & 0xFF;

                send(s_client_socket, header, 4, 0);
                send(s_client_socket, fb->buf, fb->len, 0);
                
                esp_camera_fb_return(fb);
                ESP_LOGI(TAG, "Frame sent, size: %lu bytes", (unsigned long)frame_size);
            }
        }

        close(s_client_socket);
        s_client_socket = -1;
    }

    close(server_socket);
    vTaskDelete(NULL);
}

// ===========================
// 主函数
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP32-S3 Camera Server (Station Mode)");
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
    ESP_LOGI(TAG, "[系统] NVV初始化成功");

    // 初始化WiFi Station
    wifi_sta_init();

    // 初始化摄像头
    ESP_LOGI(TAG, "[Camera] 初始化摄像头...");
    camera_init();
    ESP_LOGI(TAG, "[Camera] 摄像头初始化成功 (QQVGA 160x120 灰度)");

    // 创建UDP发现任务
    ESP_LOGI(TAG, "[系统] 启动UDP发现服务...");
    xTaskCreate(udp_discovery_task, "udp_discovery", 4096, NULL, 5, NULL);

    // 创建TCP服务器任务
    ESP_LOGI(TAG, "[系统] 启动TCP服务器...");
    xTaskCreate(tcp_server_task, "tcp_server", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "========================================");
}
