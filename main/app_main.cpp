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
#include "driver/ledc.h"
#include "driver/gpio.h"
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
// 电机引脚定义 (TB6612FNG)
// ===========================
#define MOTOR_A_PWM   GPIO_NUM_1    // GPIO1  - PWMA
#define MOTOR_A_IN1   GPIO_NUM_2    // GPIO2  - AIN1
#define MOTOR_A_IN2   GPIO_NUM_42   // GPIO42 - AIN2

#define MOTOR_B_PWM   GPIO_NUM_41   // GPIO41 - PWMB
#define MOTOR_B_IN1   GPIO_NUM_40   // GPIO40 - BIN1
#define MOTOR_B_IN2   GPIO_NUM_39   // GPIO39 - BIN2

// LEDC PWM 配置
#define MOTOR_LEDC_TIMER      LEDC_TIMER_1
#define MOTOR_LEDC_MODE       LEDC_LOW_SPEED_MODE
#define MOTOR_LEDC_RESOLUTION LEDC_TIMER_8_BIT
#define MOTOR_LEDC_FREQ       1000  // 1kHz

#define MOTOR_A_CHANNEL       LEDC_CHANNEL_1
#define MOTOR_B_CHANNEL       LEDC_CHANNEL_2

// ===========================
// WiFi AP 配置
// ===========================
#define AP_SSID      "ESP32-CAM"
#define AP_PASSWORD  "12345678"
#define AP_CHANNEL   1
#define AP_MAX_CONN  1

// TCP Server (微信小程序禁用: <1024, 8000-8100, 6000, 8888, 8443等)
#define TCP_PORT     5000
#define UDP_PORT     5001

// 图像处理相关常量
#define INPUT_WIDTH  160
#define INPUT_HEIGHT 120
#define OUTPUT_WIDTH 160
#define OUTPUT_HEIGHT 120

// UDP 视频流相关
static int g_udp_sock = -1;
static struct sockaddr_in g_udp_client_addr;
static bool g_udp_client_ready = false;

// 电机控制相关
static uint8_t g_motor_base_speed = 0;  // 基础速度PWM值 (0-255)
static bool g_motor_running = false;    // 电机运行状态

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
// 电机控制函数
// ===========================

// 初始化电机GPIO和PWM
static void motor_init(void)
{
    // 配置LEDC定时器
    ledc_timer_config_t timer_conf = {};
    timer_conf.speed_mode = MOTOR_LEDC_MODE;
    timer_conf.duty_resolution = MOTOR_LEDC_RESOLUTION;
    timer_conf.timer_num = MOTOR_LEDC_TIMER;
    timer_conf.freq_hz = MOTOR_LEDC_FREQ;
    timer_conf.clk_cfg = LEDC_AUTO_CLK;
    ledc_timer_config(&timer_conf);

    // 配置电机A PWM通道
    ledc_channel_config_t motor_a_conf = {};
    motor_a_conf.gpio_num = MOTOR_A_PWM;
    motor_a_conf.speed_mode = MOTOR_LEDC_MODE;
    motor_a_conf.channel = MOTOR_A_CHANNEL;
    motor_a_conf.intr_type = LEDC_INTR_DISABLE;
    motor_a_conf.timer_sel = MOTOR_LEDC_TIMER;
    motor_a_conf.duty = 0;
    motor_a_conf.hpoint = 0;
    ledc_channel_config(&motor_a_conf);

    // 配置电机B PWM通道
    ledc_channel_config_t motor_b_conf = {};
    motor_b_conf.gpio_num = MOTOR_B_PWM;
    motor_b_conf.speed_mode = MOTOR_LEDC_MODE;
    motor_b_conf.channel = MOTOR_B_CHANNEL;
    motor_b_conf.intr_type = LEDC_INTR_DISABLE;
    motor_b_conf.timer_sel = MOTOR_LEDC_TIMER;
    motor_b_conf.duty = 0;
    motor_b_conf.hpoint = 0;
    ledc_channel_config(&motor_b_conf);

    // 配置方向控制GPIO
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << MOTOR_A_IN1) | (1ULL << MOTOR_A_IN2) |
                           (1ULL << MOTOR_B_IN1) | (1ULL << MOTOR_B_IN2);
    io_conf.mode = GPIO_MODE_OUTPUT;
    io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&io_conf);

    // 初始状态：停止
    gpio_set_level(MOTOR_A_IN1, 0);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 0);
    gpio_set_level(MOTOR_B_IN2, 0);

    ESP_LOGI(TAG, "[Motor] 初始化完成");
}

// 电机A正转
static void motor_a_forward(uint8_t speed)
{
    gpio_set_level(MOTOR_A_IN1, 1);
    gpio_set_level(MOTOR_A_IN2, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_A_CHANNEL, speed);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_A_CHANNEL);
    ESP_LOGI(TAG, "[MotorA] 正转 速度=%d", speed);
}

// 电机B正转
static void motor_b_forward(uint8_t speed)
{
    gpio_set_level(MOTOR_B_IN1, 1);
    gpio_set_level(MOTOR_B_IN2, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_B_CHANNEL, speed);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_B_CHANNEL);
    ESP_LOGI(TAG, "[MotorB] 正转 速度=%d", speed);
}

// 停止所有电机
static void motor_stop(void)
{
    gpio_set_level(MOTOR_A_IN1, 0);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 0);
    gpio_set_level(MOTOR_B_IN2, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_A_CHANNEL, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_B_CHANNEL, 0);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_A_CHANNEL);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_B_CHANNEL);
    ESP_LOGI(TAG, "[Motor] 停止");
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
// UDP 初始化
// ===========================
static void udp_init(void)
{
    g_udp_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sock < 0) {
        ESP_LOGE(TAG, "[UDP] 创建socket失败");
        return;
    }

    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_port = htons(UDP_PORT);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(g_udp_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "[UDP] bind失败");
        close(g_udp_sock);
        g_udp_sock = -1;
        return;
    }

    ESP_LOGI(TAG, "[UDP] UDP socket已启动, 端口=%d", UDP_PORT);
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

        if (strncmp(buf, "START:", 6) == 0) {
            int speed = atoi(buf + 6);
            if (speed >= 1 && speed <= 20) {
                g_motor_running = true;
                g_motor_base_speed = speed * 255 / 100;
                motor_a_forward(g_motor_base_speed);
                motor_b_forward(g_motor_base_speed);
                ESP_LOGI(TAG, "[Motor] 启动速度%d%%, PWM=%d", speed, g_motor_base_speed);
            }
        }
        else if (strncmp(buf, "SPEED:", 6) == 0) {
            if (!g_motor_running) {
                ESP_LOGI(TAG, "[Motor] 电机未启动，忽略SPEED命令");
                continue;
            }
            int speed = atoi(buf + 6);
            if (speed >= 1 && speed <= 20) {
                g_motor_base_speed = speed * 255 / 100;  // 1-20映射到PWM百分比
                motor_a_forward(g_motor_base_speed);
                motor_b_forward(g_motor_base_speed);
                ESP_LOGI(TAG, "[Motor] 速度设置为%d%%, PWM=%d", speed, g_motor_base_speed);
            }
        }
        else if (strncmp(buf, "MOTOR_LEFT", 10) == 0) {
            if (!g_motor_running) continue;
            motor_a_forward(g_motor_base_speed);
            motor_b_forward(g_motor_base_speed / 2);
            ESP_LOGI(TAG, "[Motor] 左转: A=%d, B=%d", g_motor_base_speed, g_motor_base_speed / 2);
        }
        else if (strncmp(buf, "MOTOR_RIGHT", 11) == 0) {
            if (!g_motor_running) continue;
            motor_b_forward(g_motor_base_speed);
            motor_a_forward(g_motor_base_speed / 2);
            ESP_LOGI(TAG, "[Motor] 右转: A=%d, B=%d", g_motor_base_speed / 2, g_motor_base_speed);
        }
        else if (strncmp(buf, "MOTOR_FORWARD", 13) == 0) {
            if (!g_motor_running) continue;
            motor_a_forward(g_motor_base_speed);
            motor_b_forward(g_motor_base_speed);
            ESP_LOGI(TAG, "[Motor] 直行: A=%d, B=%d", g_motor_base_speed, g_motor_base_speed);
        }
        else if (strncmp(buf, "STOP", 4) == 0) {
            motor_stop();
            g_motor_base_speed = 0;
            g_motor_running = false;
            ESP_LOGI(TAG, "[Motor] 收到STOP命令，电机已停止");
        }
        else if (strncmp(buf, "CAPTURE", 7) == 0) {
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
        else if (strncmp(buf, "UDP_HELLO", 9) == 0) {
            // 解析客户端UDP端口: UDP_HELLO:端口
            int client_udp_port = 0;
            char *port_str = strchr(buf, ':');
            if (port_str) {
                client_udp_port = atoi(port_str + 1);
            }
            
            ESP_LOGI(TAG, "========== UDP_HELLO ==========");
            ESP_LOGI(TAG, "[UDP] 收到UDP_HELLO, 端口=%d", client_udp_port);
            ESP_LOGI(TAG, "[UDP] UDP socket状态: %s", g_udp_sock >= 0 ? "OK" : "FAILED");
            
            if (client_udp_port > 0 && g_udp_sock >= 0) {
                // 获取客户端IP (从TCP连接中获取)
                struct sockaddr_in tcp_client_addr;
                socklen_t addr_len = sizeof(tcp_client_addr);
                getpeername(client_sock, (struct sockaddr *)&tcp_client_addr, &addr_len);
                
                // 设置UDP目标地址
                g_udp_client_addr.sin_family = AF_INET;
                g_udp_client_addr.sin_addr = tcp_client_addr.sin_addr;
                g_udp_client_addr.sin_port = htons(client_udp_port);
                g_udp_client_ready = true;
                
                ESP_LOGI(TAG, "[UDP] 客户端UDP地址: %s:%d", 
                         inet_ntoa(g_udp_client_addr.sin_addr), client_udp_port);
                ESP_LOGI(TAG, "[UDP] UDP客户端就绪!");
                ESP_LOGI(TAG, "================================");
                
                // 回复确认
                send(client_sock, "UDP_OK\n", 7, 0);
            } else {
                ESP_LOGE(TAG, "[UDP] UDP_HELLO处理失败: port=%d, sock=%d", 
                         client_udp_port, g_udp_sock);
            }
        }
        else if (strncmp(buf, "STREAM", 6) == 0) {
            ESP_LOGI(TAG, "========== STREAM 开始 ==========");
            ESP_LOGI(TAG, "[Stream] UDP状态: ready=%d, sock=%d", g_udp_client_ready, g_udp_sock);
            
            if (!g_udp_client_ready || g_udp_sock < 0) {
                ESP_LOGE(TAG, "[Stream] UDP未就绪，请先发送UDP_HELLO");
                send(client_sock, "UDP_NOT_READY\n", 14, 0);
                ESP_LOGI(TAG, "================================");
                continue;
            }
            
            ESP_LOGI(TAG, "[Stream] UDP目标: %s:%d", 
                     inet_ntoa(g_udp_client_addr.sin_addr), 
                     ntohs(g_udp_client_addr.sin_port));
            ESP_LOGI(TAG, "[Stream] 帧大小: %d bytes, 分片数: 4", INPUT_WIDTH * INPUT_HEIGHT);
            ESP_LOGI(TAG, "================================");
            
            int frame_count = 0;
            bool streaming = true;
            int64_t stream_start_time = esp_timer_get_time();
            
            // 分片参数
            const uint32_t frame_size = INPUT_WIDTH * INPUT_HEIGHT;  // 19200
            const int total_chunks = 3;
            const int chunk_size = 8000;  // 每分片最大8000字节
            const int last_chunk_size = frame_size - chunk_size * (total_chunks - 1);  // 3200
            
            while (streaming) {
                int64_t frame_start = esp_timer_get_time();
                
                camera_fb_t *fb = esp_camera_fb_get();
                if (!fb) {
                    ESP_LOGE(TAG, "[Stream] 帧%d: 采集失败", frame_count);
                    continue;
                }

                // UDP分片发送
                int chunks_sent = 0;
                for (int i = 0; i < total_chunks; i++) {
                    // 计算当前分片数据大小和偏移
                    int current_chunk_size = (i == total_chunks - 1) ? last_chunk_size : chunk_size;
                    int offset = i * chunk_size;
                    
                    // 分片缓冲区: [帧号2字节][总分片数1字节][分片索引1字节][数据]
                    uint8_t *chunk_buf = (uint8_t *)malloc(4 + current_chunk_size);
                    if (chunk_buf) {
                        // 协议头
                        chunk_buf[0] = (frame_count >> 8) & 0xFF;    // 帧号高字节
                        chunk_buf[1] = frame_count & 0xFF;           // 帧号低字节
                        chunk_buf[2] = total_chunks;                  // 总分片数
                        chunk_buf[3] = i;                             // 当前分片索引
                        
                        // 复制数据
                        memcpy(chunk_buf + 4, fb->buf + offset, current_chunk_size);
                        
                        // 发送UDP分片
                        int sent = sendto(g_udp_sock, chunk_buf, 4 + current_chunk_size, 0,
                                          (struct sockaddr *)&g_udp_client_addr, 
                                          sizeof(g_udp_client_addr));
                        
                        if (sent > 0) {
                            chunks_sent++;
                        }
                        free(chunk_buf);
                    }
                }
                
                int64_t frame_end = esp_timer_get_time();
                float frame_time = (frame_end - frame_start) / 1000.0f;
                
                if (chunks_sent == total_chunks) {
                    frame_count++;
                    // 每100帧打印一次状态
                    if (frame_count % 100 == 0) {
                        float fps = frame_count * 1000.0f / ((frame_end - stream_start_time) / 1000.0f);
                        ESP_LOGI(TAG, "[Stream] 帧%d: 发送%d分片, 耗时%.1fms, FPS=%.1f", 
                                 frame_count, chunks_sent, frame_time, fps);
                    }
                } else {
                    ESP_LOGE(TAG, "[Stream] 帧%d: 分片发送不完整 %d/%d", 
                             frame_count, chunks_sent, total_chunks);
                }

                esp_camera_fb_return(fb);

                // 非阻塞检查命令
                int len = recv(client_sock, buf, sizeof(buf) - 1, MSG_DONTWAIT);
                if (len > 0) {
                    buf[len] = '\0';
                    ESP_LOGI(TAG, "[TCP] 收到命令: %s", buf);
                    
                    if (strncmp(buf, "START:", 6) == 0) {
                        int speed = atoi(buf + 6);
                        if (speed >= 1 && speed <= 20) {
                            g_motor_running = true;
                            g_motor_base_speed = speed * 255 / 100;
                            motor_a_forward(g_motor_base_speed);
                            motor_b_forward(g_motor_base_speed);
                            ESP_LOGI(TAG, "[Motor] 启动速度%d%%, PWM=%d", speed, g_motor_base_speed);
                        }
                    }
                    else if (strncmp(buf, "STOP_STREAM", 11) == 0) {
                        motor_stop();
                        g_motor_base_speed = 0;
                        g_motor_running = false;
                        streaming = false;
                        ESP_LOGI(TAG, "[Stream] 收到STOP_STREAM命令，停止视频流");
                    }
                    else if (strncmp(buf, "STOP", 4) == 0) {
                        motor_stop();
                        g_motor_base_speed = 0;
                        g_motor_running = false;
                        ESP_LOGI(TAG, "[Motor] 收到STOP命令，电机已停止");
                    }
                    else if (strncmp(buf, "SPEED:", 6) == 0) {
                        if (!g_motor_running) {
                            ESP_LOGI(TAG, "[Motor] 电机未启动，忽略SPEED命令");
                            continue;
                        }
                        int speed = atoi(buf + 6);
                        if (speed >= 1 && speed <= 20) {
                            g_motor_base_speed = speed * 255 / 100;
                            motor_a_forward(g_motor_base_speed);
                            motor_b_forward(g_motor_base_speed);
                            ESP_LOGI(TAG, "[Motor] 速度设置为%d%%, PWM=%d", speed, g_motor_base_speed);
                        }
                    }
                    else if (strncmp(buf, "MOTOR_LEFT", 10) == 0) {
                        if (!g_motor_running) continue;
                        motor_a_forward(g_motor_base_speed);
                        motor_b_forward(g_motor_base_speed / 2);
                        ESP_LOGI(TAG, "[Motor] 左转: A=%d, B=%d", g_motor_base_speed, g_motor_base_speed / 2);
                    }
                    else if (strncmp(buf, "MOTOR_RIGHT", 11) == 0) {
                        if (!g_motor_running) continue;
                        motor_b_forward(g_motor_base_speed);
                        motor_a_forward(g_motor_base_speed / 2);
                        ESP_LOGI(TAG, "[Motor] 右转: A=%d, B=%d", g_motor_base_speed / 2, g_motor_base_speed);
                    }
                    else if (strncmp(buf, "MOTOR_FORWARD", 13) == 0) {
                        if (!g_motor_running) continue;
                        motor_a_forward(g_motor_base_speed);
                        motor_b_forward(g_motor_base_speed);
                        ESP_LOGI(TAG, "[Motor] 直行: A=%d, B=%d", g_motor_base_speed, g_motor_base_speed);
                    }
                }

                // 小延时，控制帧率
                vTaskDelay(pdMS_TO_TICKS(20));
            }
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
    motor_init();
    wifi_init_ap();
    udp_init();

    // TCP服务器任务绑定到Core 1，推理任务与WiFi底层(Core 0)分离
    xTaskCreatePinnedToCore(tcp_server_task, "tcp_server", 8192, NULL, 5, NULL, 1);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s  密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "TCP端口: %d  UDP端口: %d", TCP_PORT, UDP_PORT);
    ESP_LOGI(TAG, "========================================");
}
