/**
 * ESP32 模型测试固件
 * 功能：通过TCP接收图片，进行模型推理，返回二值图结果
 * 编译：将此文件改名为 app_main.cpp 后编译
 */

#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "lwip/ip_addr.h"
#include "lwip/sockets.h"
#include "esp_timer.h"
#include "dl_model_base.hpp"

static const char *TAG = "TEST_MODEL";

// 声明嵌入的模型数据
extern const uint8_t model_espdl[] asm("_binary_model_espdl_start");

// 全局模型指针
static dl::Model *g_model = nullptr;

// 图像尺寸
#define INPUT_WIDTH  160
#define INPUT_HEIGHT 120

// WiFi AP 配置
#define AP_SSID      "ESP32-TEST"
#define AP_PASSWORD  "12345678"
#define AP_CHANNEL   1
#define AP_MAX_CONN  1

// TCP端口
#define TCP_PORT     5000

// Sigmoid查表
static uint8_t sigmoid_lut[256];

static void init_sigmoid_lut(void)
{
    for (int i = 0; i < 256; i++) {
        int8_t q = (int8_t)i;
        float x = q / 128.0f;
        float sig = 1.0f / (1.0f + expf(-x));
        sigmoid_lut[i] = (sig > 0.5f) ? 255 : 0;
    }
}

// WiFi AP 初始化
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

// 处理客户端
static void handle_client(int client_sock)
{
    ESP_LOGI(TAG, "[TCP] 客户端已连接");

    // 握手
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
    snprintf(device_info, sizeof(device_info), "TestModel V1|🧪|%02X:%02X:%02X:%02X:%02X:%02X\n",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    send(client_sock, device_info, strlen(device_info), 0);
    ESP_LOGI(TAG, "[TCP] 握手成功: %s", device_info);

    char buf[64];
    uint8_t *image_buf = (uint8_t *)malloc(INPUT_WIDTH * INPUT_HEIGHT);
    uint8_t *pred_buf = (uint8_t *)malloc(INPUT_WIDTH * INPUT_HEIGHT);

    while (1) {
        int len = recv(client_sock, buf, sizeof(buf) - 1, 0);
        if (len <= 0) {
            ESP_LOGI(TAG, "[TCP] 客户端断开");
            break;
        }
        buf[len] = '\0';

        if (strncmp(buf, "PREDICT", 7) == 0) {
            ESP_LOGI(TAG, "[PREDICT] 收到PREDICT命令");
            
            // 等待数据分离
            vTaskDelay(pdMS_TO_TICKS(10));
            
            // 接收图片大小 (4字节)
            uint8_t size_buf[4];
            int received = recv(client_sock, (char *)size_buf, 4, MSG_WAITALL);
            if (received != 4) {
                ESP_LOGE(TAG, "[PREDICT] 接收大小失败: received=%d", received);
                continue;
            }

            uint32_t image_size = (size_buf[0] << 24) | (size_buf[1] << 16) | 
                                  (size_buf[2] << 8) | size_buf[3];
            
            ESP_LOGI(TAG, "[PREDICT] 接收图片大小: %lu bytes", (unsigned long)image_size);

            // 接收图片数据
            uint32_t offset = 0;
            while (offset < image_size) {
                int chunk = recv(client_sock, (char *)(image_buf + offset), image_size - offset, 0);
                if (chunk <= 0) {
                    ESP_LOGE(TAG, "[PREDICT] 接收图片失败");
                    break;
                }
                offset += chunk;
            }

            if (offset != image_size) {
                ESP_LOGE(TAG, "[PREDICT] 图片数据不完整: %lu/%lu", (unsigned long)offset, (unsigned long)image_size);
                continue;
            }

            ESP_LOGI(TAG, "[PREDICT] 图片接收完成，开始推理...");

            // 模型推理
            int64_t t_start = esp_timer_get_time();

            // 获取模型输入tensor
            dl::TensorBase *input_tensor = g_model->get_input("input");
            uint8_t *model_input = (uint8_t *)input_tensor->data;
            
            // 复制图像到模型输入
            memcpy(model_input, image_buf, INPUT_WIDTH * INPUT_HEIGHT);

            // 执行推理
            g_model->run();
            dl::TensorBase *output_tensor = g_model->get_output("output");
            int8_t *output_data = (int8_t *)output_tensor->data;

            // 后处理: sigmoid查表
            for (int i = 0; i < INPUT_WIDTH * INPUT_HEIGHT; i++) {
                uint8_t idx = (uint8_t)(output_data[i] + 128);
                pred_buf[i] = sigmoid_lut[idx];
            }

            int64_t t_end = esp_timer_get_time();
            ESP_LOGI(TAG, "[PREDICT] 推理完成，耗时 %.1f ms", (t_end - t_start) / 1000.0);

            // 发送结果大小 (4字节)
            uint32_t result_size = INPUT_WIDTH * INPUT_HEIGHT;
            uint8_t result_size_buf[4];
            result_size_buf[0] = (result_size >> 24) & 0xFF;
            result_size_buf[1] = (result_size >> 16) & 0xFF;
            result_size_buf[2] = (result_size >> 8) & 0xFF;
            result_size_buf[3] = result_size & 0xFF;
            send(client_sock, result_size_buf, 4, 0);

            // 发送二值图数据
            offset = 0;
            while (offset < result_size) {
                int chunk = result_size - offset;
                if (chunk > 1460) chunk = 1460;
                int sent = send(client_sock, pred_buf + offset, chunk, 0);
                if (sent < 0) {
                    ESP_LOGE(TAG, "[PREDICT] 发送结果失败");
                    break;
                }
                offset += sent;
            }

            ESP_LOGI(TAG, "[PREDICT] 结果发送完成: %lu bytes", (unsigned long)result_size);
        }
        else if (strncmp(buf, "EXIT", 4) == 0) {
            ESP_LOGI(TAG, "[TCP] 收到EXIT命令，断开连接");
            break;
        }
    }

    free(image_buf);
    free(pred_buf);
    close(client_sock);
}

// TCP Server 任务
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

extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "ESP32 模型测试固件");
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

    wifi_init_ap();

    xTaskCreatePinnedToCore(tcp_server_task, "tcp_server", 8192, NULL, 5, NULL, 1);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s  密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "TCP端口: %d", TCP_PORT);
    ESP_LOGI(TAG, "========================================");
}
