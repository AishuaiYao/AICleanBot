#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_camera.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "lwip/ip_addr.h"
#include "lwip/sockets.h"
#include "esp_timer.h"
#include "dl_model_base.hpp"

static const char *TAG = "CAM_TCP";

// 声明嵌入的模型数据
extern const uint8_t model_espdl[] asm("_binary_model_espdl_start");

// 全局模型指针
static dl::Model *g_model = nullptr;

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

// 图像处理相关常量
#define INPUT_WIDTH  160
#define INPUT_HEIGHT 120
#define OUTPUT_WIDTH 160
#define OUTPUT_HEIGHT 120

// ===========================
// Sigmoid查表优化
// ===========================
static uint8_t sigmoid_lut[256];  // sigmoid查表（256字节）

// 初始化sigmoid查表
static void init_sigmoid_lut(void)
{
    for (int i = 0; i < 256; i++) {
        int8_t q = (int8_t)i;  // int8量化值: -128~127
        float x = q / 128.0f;  // 反量化
        float sig = 1.0f / (1.0f + expf(-x));
        sigmoid_lut[i] = (sig > 0.5f) ? 255 : 0;  // 直接存储二值结果
    }
}

// ===========================
// 图像处理函数
// ===========================

// Sigmoid函数（保留备用）
float sigmoid(float x)
{
    return 1.0f / (1.0f + expf(-x));
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

    // ========== 握手协议 ==========
    char handshake_buf[64];
    int handshake_len = recv(client_sock, handshake_buf, sizeof(handshake_buf) - 1, 0);
    if (handshake_len <= 0 || strncmp(handshake_buf, "HELLO", 5) != 0) {
        ESP_LOGI(TAG, "[TCP] 握手失败");
        close(client_sock);
        return;
    }

    // 获取MAC地址
    uint8_t mac[6];
    esp_wifi_get_mac(WIFI_IF_AP, mac);
    char device_info[64];
    snprintf(device_info, sizeof(device_info), "LinePatrol V1|😊|%02X:%02X:%02X:%02X:%02X:%02X\n",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    send(client_sock, device_info, strlen(device_info), 0);
    ESP_LOGI(TAG, "[TCP] 握手成功: %s", device_info);

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
            int64_t t_start = esp_timer_get_time();

            int64_t t1 = esp_timer_get_time();
            camera_fb_t *fb = esp_camera_fb_get();
            int64_t t2 = esp_timer_get_time();

            if (!fb) {
                ESP_LOGE(TAG, "[Camera] 采集失败! 耗时%.1fms", (t2 - t1) / 1000.0);
                const char *err = "ERROR\n";
                send(client_sock, err, strlen(err), 0);
                continue;
            }

            ESP_LOGI(TAG, "[Camera] 采集成功: %dx%d, 大小=%lu bytes, 耗时%.1fms",
                     fb->width, fb->height, (unsigned long)fb->len, (t2 - t1) / 1000.0);

            // ========== 图像预处理 ==========
            int64_t t3 = esp_timer_get_time();
            
            // 获取模型输入 tensor
            dl::TensorBase *input_tensor = g_model->get_input("input");
            std::vector<int> in_shape = input_tensor->get_shape();
            ESP_LOGI(TAG, "[Input] Tensor shape: %d x %d x %d x %d", 
                     in_shape.size() > 0 ? in_shape[0] : 0,
                     in_shape.size() > 1 ? in_shape[1] : 0,
                     in_shape.size() > 2 ? in_shape[2] : 0,
                     in_shape.size() > 3 ? in_shape[3] : 0);
            
            uint8_t *model_input = (uint8_t *)input_tensor->data;
            
            // 直接复制原始图像到模型输入 (不resize)
            memcpy(model_input, fb->buf, INPUT_WIDTH * INPUT_HEIGHT);
            
            int64_t t4 = esp_timer_get_time();
            ESP_LOGI(TAG, "[Preprocess] 预处理耗时%.1fms", (t4 - t3) / 1000.0);

            // ========== 模型推理 ==========
            int64_t t5 = esp_timer_get_time();
            
            // 执行推理
            g_model->run();
            dl::TensorBase *output_tensor = g_model->get_output("output");
            
            int64_t t6 = esp_timer_get_time();
            ESP_LOGI(TAG, "[Inference] 模型推理耗时%.1fms", (t6 - t5) / 1000.0);
            
            // ========== 后处理 ==========
            int64_t t7 = esp_timer_get_time();
            
            // 打印输出 tensor 信息
            std::vector<int> out_shape = output_tensor->get_shape();
            ESP_LOGI(TAG, "[Output] Tensor shape: %d x %d x %d x %d", 
                     out_shape.size() > 0 ? out_shape[0] : 0,
                     out_shape.size() > 1 ? out_shape[1] : 0,
                     out_shape.size() > 2 ? out_shape[2] : 0,
                     out_shape.size() > 3 ? out_shape[3] : 0);
            ESP_LOGI(TAG, "[Output] Tensor size: %d, dtype: %d", output_tensor->size, output_tensor->dtype);
            
            // 获取输出数据
            int8_t *output_data = (int8_t *)output_tensor->data;
            
            // 分配预测图缓冲区
            uint8_t *pred_data = (uint8_t *)malloc(OUTPUT_WIDTH * OUTPUT_HEIGHT);
            
            // 后处理: sigmoid查表 + 阈值分割 (输出尺寸与输入相同，无需resize)
            for (int i = 0; i < OUTPUT_WIDTH * OUTPUT_HEIGHT; i++) {
                uint8_t idx = (uint8_t)(output_data[i] + 128);  // int8转uint8索引(0~255)
                pred_data[i] = sigmoid_lut[idx];  // 直接查表
            }
            
            int64_t t8 = esp_timer_get_time();
            ESP_LOGI(TAG, "[Postprocess] 后处理耗时%.1fms", (t8 - t7) / 1000.0);
            
            // ========== 横向拼接 ==========
            uint32_t concat_size = OUTPUT_WIDTH * 2 * OUTPUT_HEIGHT;  // 320x120
            uint8_t *concat_data = (uint8_t *)malloc(concat_size);
            
            for (int y = 0; y < OUTPUT_HEIGHT; y++) {
                // 左侧：原图
                memcpy(concat_data + y * OUTPUT_WIDTH * 2, 
                       fb->buf + y * OUTPUT_WIDTH, 
                       OUTPUT_WIDTH);
                // 右侧：预测图
                memcpy(concat_data + y * OUTPUT_WIDTH * 2 + OUTPUT_WIDTH, 
                       pred_data + y * OUTPUT_WIDTH, 
                       OUTPUT_WIDTH);
            }
            
            int64_t t9 = esp_timer_get_time();
            ESP_LOGI(TAG, "[Concat] 拼接耗时%.1fms", (t9 - t8) / 1000.0);

            // ========== 发送图像 ==========
            uint8_t header[4];
            uint32_t frame_size = concat_size;
            header[0] = (frame_size >> 24) & 0xFF;
            header[1] = (frame_size >> 16) & 0xFF;
            header[2] = (frame_size >> 8) & 0xFF;
            header[3] = frame_size & 0xFF;

            send(client_sock, header, 4, 0);

            // 分块发送图像数据
            uint32_t offset = 0;
            while (offset < frame_size) {
                int chunk = frame_size - offset;
                if (chunk > 1460) chunk = 1460;
                int sent = send(client_sock, concat_data + offset, chunk, 0);
                if (sent < 0) {
                    ESP_LOGE(TAG, "[TCP] 发送失败");
                    break;
                }
                offset += sent;
            }

            int64_t t10 = esp_timer_get_time();
            ESP_LOGI(TAG, "[TCP] 图像发送完成: %lu bytes, 传输耗时%.1fms, 总耗时%.1fms",
                     (unsigned long)frame_size, (t10 - t9) / 1000.0, (t10 - t_start) / 1000.0);
            
            // 释放内存
            free(pred_data);
            
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

    // 初始化sigmoid查表
    init_sigmoid_lut();
    ESP_LOGI(TAG, "[Init] Sigmoid查表初始化完成");

    // 初始化模型
    ESP_LOGI(TAG, "[Model] 加载模型...");
    g_model = new dl::Model((const char *)model_espdl, fbs::MODEL_LOCATION_IN_FLASH_RODATA);
    ESP_ERROR_CHECK(g_model->test());
    g_model->profile();
    
    // 打印模型输入输出名称
    auto &model_inputs = g_model->get_inputs();
    auto &model_outputs = g_model->get_outputs();
    ESP_LOGI(TAG, "[Model] 输入数量: %d", model_inputs.size());
    for (auto &pair : model_inputs) {
        ESP_LOGI(TAG, "[Model] 输入名称: %s", pair.first.c_str());
    }
    ESP_LOGI(TAG, "[Model] 输出数量: %d", model_outputs.size());
    for (auto &pair : model_outputs) {
        ESP_LOGI(TAG, "[Model] 输出名称: %s", pair.first.c_str());
    }
    
    ESP_LOGI(TAG, "[Model] 模型加载成功");

    camera_init();
    wifi_init_ap();

    // TCP服务器任务绑定到Core 1，推理任务与WiFi底层(Core 0)分离
    xTaskCreatePinnedToCore(tcp_server_task, "tcp_server", 8192, NULL, 5, NULL, 1);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s  密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "TCP端口: %d", TCP_PORT);
    ESP_LOGI(TAG, "========================================");
}
