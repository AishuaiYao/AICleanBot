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
#include "driver/pulse_cnt.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_ota_ops.h"
#include "dl_model_base.hpp"
#include "dl_tool.hpp"

static const char *TAG = "CAM_TCP";

// snprintf 返回的是"未截断长度"，直接拿它当发送长度会在格式化被截断时越界读写，
// 统一钳到缓冲区容量内，并预留一位给结尾换行
#define SNPRINTF_LEN(ret, cap) (((ret) < 0) ? 0 : \
    (((size_t)(ret) >= (size_t)(cap)) ? (int)(cap) - 1 : (int)(ret)))

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
// 左轮（IN1/IN2已与右轮并联，共享GPIO）
#define MOTOR_L_PWM   GPIO_NUM_39    // 左轮PWMB（速度控制）
#define MOTOR_L_IN1   GPIO_NUM_2     // 左轮BIN1（与右轮共享GPIO2）
#define MOTOR_L_IN2   GPIO_NUM_42    // 左轮BIN2（与右轮共享GPIO42）
// 右轮
#define MOTOR_R_PWM   GPIO_NUM_14   // 右轮PWMA（速度控制）
#define MOTOR_R_IN1   GPIO_NUM_2     // 右轮AIN1（方向控制）
#define MOTOR_R_IN2   GPIO_NUM_42    // 右轮AIN2（方向控制）
// 3号电机
#define MOTOR3_PWM        GPIO_NUM_45    // 3号电机PWM
#define MOTOR3_CHANNEL    LEDC_CHANNEL_4 // 通道4，共享Timer1
#define MOTOR3_INIT_DUTY  51              // 初始占空比20% (8位: 255*20%≈51)

// ===========================
// 编码器引脚定义
// ===========================
#define ENCODER_L_A   GPIO_NUM_47    // 左编码器E2A
#define ENCODER_L_B   GPIO_NUM_21    // 左编码器E2B
#define ENCODER_R_A   GPIO_NUM_41    // 右编码器E1A
#define ENCODER_R_B   GPIO_NUM_40    // 右编码器E1B

// ===========================
// 电池ADC引脚定义
// ===========================
#define BAT_ADC_CHANNEL  ADC_CHANNEL_0  // GPIO1 = ADC1_CH0
#define BAT_VOLTAGE_DIVIDER  11          // 分压比例 1/11

// ===========================
// 呼吸灯LED引脚定义
// ===========================
#define BREATH_LED_GPIO     GPIO_NUM_38   // 呼吸灯GPIO
#define BREATH_LED_CHANNEL  LEDC_CHANNEL_3  // 使用通道3（0/1/2已被占用）
#define BREATH_LED_TIMER    LEDC_TIMER_2    // 使用定时器2

// LEDC PWM 配置
#define MOTOR_LEDC_TIMER      LEDC_TIMER_1
#define MOTOR_LEDC_MODE       LEDC_LOW_SPEED_MODE
#define MOTOR_LEDC_RESOLUTION LEDC_TIMER_8_BIT
#define MOTOR_LEDC_FREQ       1000  // 1kHz

#define MOTOR_L_CHANNEL       LEDC_CHANNEL_1
#define MOTOR_R_CHANNEL       LEDC_CHANNEL_2

// ===========================
// WiFi AP 配置
// ===========================
#define AP_SSID      "LinePatrol V1"
// 改成你自己的热点密码。
// 注意：WPA2 要求密码至少 8 位，下面 8 个星号只是占位符，
// 若保持原样 esp_wifi_start() 也能通过，但任何人都能连上你的设备。
#define AP_PASSWORD  "********"
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
static uint8_t g_motor_l_pwm = 0;       // 左电机实际PWM值
static uint8_t g_motor_r_pwm = 0;       // 右电机实际PWM值

// PID控制相关
static float g_pid_kp = 0.5f;           // 比例系数，默认0.5
static float g_smoothed_error = 0.0f;   // 平滑后的误差（指数滑动平均）
static int g_line_lost_count = 0;       // 连续丢线帧数

// 编码器相关 - PCNT外设
static pcnt_unit_handle_t g_pcnt_l = NULL;  // 左轮 PCNT 单元句柄
static pcnt_unit_handle_t g_pcnt_r = NULL;  // 右轮 PCNT 单元句柄

// ===========================
// Sigmoid查表优化
// ===========================
static uint8_t sigmoid_lut[256];  // sigmoid查表（256字节）

// 初始化sigmoid查表（根据模型输出量化参数构建）
static void init_sigmoid_lut(float out_scale)
{
    for (int i = 0; i < 256; i++) {
        int8_t q = (int8_t)(i - 128);   // uint8索引 -> int8值
        float logits = q * out_scale;   // 反量化
        float sig = 1.0f / (1.0f + expf(-logits));
        sigmoid_lut[i] = (sig > 0.5f) ? 255 : 0;
    }
}

// ===========================
// 输入量化查表
// ===========================
static int8_t input_quant_lut[256];  // 灰度值查表（256字节）

// 初始化输入量化查表（根据模型输入量化参数构建）
// 预处理是每帧 19200 像素的循环，查表把逐像素浮点归一化+量化换成一次数组访问
static void init_input_quant_lut(float in_inv_scale)
{
    for (int i = 0; i < 256; i++) {
        float normalized = i / 255.0f;
        input_quant_lut[i] = (int8_t)DL_CLIP(dl::tool::round(normalized * in_inv_scale), -128, 127);
    }
}

// 原地旋转图像180度 (swap首尾像素)
static void rotate_180_inplace(uint8_t* buf, int width, int height)
{
    int total = width * height;
    for (int i = 0; i < total / 2; i++) {
        uint8_t tmp = buf[i];
        buf[i] = buf[total - 1 - i];
        buf[total - 1 - i] = tmp;
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

// 计算指定行的质心（使用连通区域检测）
static float calc_line_centroid(uint8_t* pred, int width, int line_y)
{
    int sum_x = 0;
    int count = 0;
    int start_x = -1;
    
    for (int x = 0; x < width; x++) {
        if (pred[line_y * width + x] > 128) {
            if (start_x < 0) start_x = x;
            sum_x += x;
            count++;
        } else {
            if (start_x >= 0 && count > 0) {
                // 区域结束，返回这个区域的质心
                return (float)sum_x / count;
            }
            start_x = -1;
            sum_x = 0;
            count = 0;
        }
    }
    
    // 检查最后一个区域
    if (count > 0) {
        return (float)sum_x / count;
    }
    return -1.0f;
}

// 从预测图中计算顶部和底部质心坐标
// g1: 输出顶部质心x坐标（图像上方区域）
// g2: 输出底部质心x坐标（图像下方区域）
// 返回true表示两个点都有效，false表示丢线
static bool calc_centroids(uint8_t* pred, int width, int height, float* g1, float* g2)
{
    const int scan_rows = 5;

    // 上5行质心 → G1
    float top_sum_x = 0, top_count = 0;
    for (int y = 0; y < scan_rows; y++) {
        float cx = calc_line_centroid(pred, width, y);
        if (cx >= 0) {
            top_sum_x += cx;
            top_count++;
        }
    }

    // 下5行质心 → G2
    float bottom_sum_x = 0, bottom_count = 0;
    for (int y = height - scan_rows; y < height; y++) {
        float cx = calc_line_centroid(pred, width, y);
        if (cx >= 0) {
            bottom_sum_x += cx;
            bottom_count++;
        }
    }

    if (top_count > 0) *g1 = top_sum_x / top_count;
    else *g1 = -1.0f;
    if (bottom_count > 0) *g2 = bottom_sum_x / bottom_count;
    else *g2 = -1.0f;

    bool ok = (*g1 >= 0 && *g2 >= 0);

    //ESP_LOGI(TAG, "[PID] calc_centroids: G1=%.1f, G2=%.1f, ok=%d", *g1, *g2, (int)ok);

    return ok;
}

// PID比例控制：基于G1/G2质心偏差
// g1: 顶部质心x坐标, g2: 底部质心x坐标, g0: 图像中点x坐标
// out_pwm: 输出增量PWM（始终>=0）
// out_turn_right: true=右转(左轮加速/右轮减速), false=左转(左轮减速/右轮加速)
static void pid_compute(float g1, float g2, int g0, int* out_pwm, bool* out_turn_right)
{
    float error;
    bool turn_right;
    const float NEAR_EQUAL_THRESH = 10.0f;  // |G1-G2| < 10 视为近似相等

    if (fabsf(g1 - g2) >= NEAR_EQUAL_THRESH) {
        // G1/G2 差距大：用 G1-G2 偏差
        if (g1 > g2) {
            turn_right = true;   // 右转
            error = g1 - g2;
        } else {
            turn_right = false;  // 左转
            error = g2 - g1;
        }
    } else {
        // G1≈G2：与中点G0比较
        float mid = (g1 + g2) / 2;
        if (mid > g0) {
            turn_right = true;
            error = mid - g0;
        } else if (mid < g0) {
            turn_right = false;
            error = g0 - mid;
        } else {
            error = 0;
            turn_right = false;
        }
    }

    *out_pwm = (int)(g_pid_kp * error);
    *out_turn_right = turn_right;

    //ESP_LOGI(TAG, "[PID] pid_compute: G1=%.1f G2=%.1f error=%.1f kp=%.2f delta=%d %s",
    //         g1, g2, error, g_pid_kp, *out_pwm, turn_right ? "RIGHT" : "LEFT");
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

    // 配置左轮PWM通道
    ledc_channel_config_t motor_l_conf = {};
    motor_l_conf.gpio_num = MOTOR_L_PWM;
    motor_l_conf.speed_mode = MOTOR_LEDC_MODE;
    motor_l_conf.channel = MOTOR_L_CHANNEL;
    motor_l_conf.intr_type = LEDC_INTR_DISABLE;
    motor_l_conf.timer_sel = MOTOR_LEDC_TIMER;
    motor_l_conf.duty = 0;
    motor_l_conf.hpoint = 0;
    ledc_channel_config(&motor_l_conf);

    // 配置右轮PWM通道
    ledc_channel_config_t motor_r_conf = {};
    motor_r_conf.gpio_num = MOTOR_R_PWM;
    motor_r_conf.speed_mode = MOTOR_LEDC_MODE;
    motor_r_conf.channel = MOTOR_R_CHANNEL;
    motor_r_conf.intr_type = LEDC_INTR_DISABLE;
    motor_r_conf.timer_sel = MOTOR_LEDC_TIMER;
    motor_r_conf.duty = 0;
    motor_r_conf.hpoint = 0;
    ledc_channel_config(&motor_r_conf);

    // 配置3号电机PWM通道
    ledc_channel_config_t motor3_conf = {};
    motor3_conf.gpio_num = MOTOR3_PWM;
    motor3_conf.speed_mode = MOTOR_LEDC_MODE;
    motor3_conf.channel = MOTOR3_CHANNEL;
    motor3_conf.intr_type = LEDC_INTR_DISABLE;
    motor3_conf.timer_sel = MOTOR_LEDC_TIMER;
    motor3_conf.duty = 0;  // 初始停止，收到START命令后才启动
    motor3_conf.hpoint = 0;
    ledc_channel_config(&motor3_conf);

    // 配置方向控制GPIO
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << MOTOR_L_IN1) | (1ULL << MOTOR_L_IN2) |
                           (1ULL << MOTOR_R_IN1) | (1ULL << MOTOR_R_IN2);
    io_conf.mode = GPIO_MODE_OUTPUT;
    io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&io_conf);

    // 初始状态：停止
    gpio_set_level(MOTOR_L_IN1, 0);
    gpio_set_level(MOTOR_L_IN2, 0);
    gpio_set_level(MOTOR_R_IN1, 0);
    gpio_set_level(MOTOR_R_IN2, 0);

    ESP_LOGI(TAG, "[Motor] 初始化完成");
}

// ===========================
// 编码器初始化 - 单通道一倍频（A相上升沿+1）
// ===========================
static void encoder_init(void)
{
    ESP_LOGI(TAG, "[Encoder] 初始化开始 (单通道一倍频)...");

    // 编码器GPIO配置（不上拉，由外部电路决定）
    gpio_config_t pull_conf = {};
    pull_conf.pin_bit_mask = (1ULL << ENCODER_L_A) | (1ULL << ENCODER_L_B) |
                             (1ULL << ENCODER_R_A) | (1ULL << ENCODER_R_B);
    pull_conf.mode = GPIO_MODE_INPUT;
    pull_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    pull_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    gpio_config(&pull_conf);

    // 配置左编码器 - 简单A相上升沿+1
    pcnt_unit_config_t unit_conf_l = {};
    unit_conf_l.high_limit = 32767;
    unit_conf_l.low_limit = -32768;
    unit_conf_l.flags.accum_count = 1;
    pcnt_new_unit(&unit_conf_l, &g_pcnt_l);

    pcnt_chan_config_t chan_la = {};
    chan_la.edge_gpio_num = ENCODER_L_A;
    chan_la.level_gpio_num = -1;
    pcnt_channel_handle_t ch_la = NULL;
    pcnt_new_channel(g_pcnt_l, &chan_la, &ch_la);
    pcnt_channel_set_edge_action(ch_la, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 配置右编码器
    pcnt_unit_config_t unit_conf_r = {};
    unit_conf_r.high_limit = 32767;
    unit_conf_r.low_limit = -32768;
    unit_conf_r.flags.accum_count = 1;
    pcnt_new_unit(&unit_conf_r, &g_pcnt_r);

    pcnt_chan_config_t chan_ra = {};
    chan_ra.edge_gpio_num = ENCODER_R_A;
    chan_ra.level_gpio_num = -1;
    pcnt_channel_handle_t ch_ra = NULL;
    pcnt_new_channel(g_pcnt_r, &chan_ra, &ch_ra);
    pcnt_channel_set_edge_action(ch_ra, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 启动
    pcnt_unit_enable(g_pcnt_l);
    pcnt_unit_enable(g_pcnt_r);
    pcnt_unit_clear_count(g_pcnt_l);
    pcnt_unit_clear_count(g_pcnt_r);
    pcnt_unit_start(g_pcnt_l);
    pcnt_unit_start(g_pcnt_r);

    ESP_LOGI(TAG, "[Encoder] 初始化完成: 左轮=GPIO%d/GPIO%d, 右轮=GPIO%d/GPIO%d",
             ENCODER_L_A, ENCODER_L_B, ENCODER_R_A, ENCODER_R_B);
}

// ===========================
// 电池ADC初始化
// ===========================
static adc_oneshot_unit_handle_t adc_handle;

static void battery_adc_init(void)
{
    ESP_LOGI(TAG, "[Battery] ADC初始化, GPIO14, 分压比1/%d...", BAT_VOLTAGE_DIVIDER);

    adc_oneshot_unit_init_cfg_t init_cfg = {};
    init_cfg.unit_id = ADC_UNIT_1;
    adc_oneshot_new_unit(&init_cfg, &adc_handle);

    adc_oneshot_chan_cfg_t chan_cfg = {};
    chan_cfg.bitwidth = ADC_BITWIDTH_12;
    chan_cfg.atten = ADC_ATTEN_DB_12;
    adc_oneshot_config_channel(adc_handle, BAT_ADC_CHANNEL, &chan_cfg);

    ESP_LOGI(TAG, "[Battery] ADC初始化完成");
}

// 读取电池电压(十分之一伏特，如120表示12.0V)
static uint8_t battery_read_voltage(void)
{
    int adc_raw;
    adc_oneshot_read(adc_handle, BAT_ADC_CHANNEL, &adc_raw);
    float voltage = adc_raw * 3.3f / 4095.0f;
    uint8_t battery_01v = (uint8_t)(voltage * BAT_VOLTAGE_DIVIDER * 10.0f);
    return battery_01v;
}

// ===========================
// 呼吸灯初始化与任务
// ===========================

// 呼吸灯PWM初始化
static void breath_led_init(void)
{
    // 配置LEDC定时器
    ledc_timer_config_t timer_conf = {};
    timer_conf.speed_mode = LEDC_LOW_SPEED_MODE;
    timer_conf.duty_resolution = LEDC_TIMER_10_BIT;  // 10位分辨率，1024级
    timer_conf.timer_num = BREATH_LED_TIMER;
    timer_conf.freq_hz = 5000;  // 5kHz
    timer_conf.clk_cfg = LEDC_AUTO_CLK;
    ledc_timer_config(&timer_conf);

    // 配置LEDC通道
    ledc_channel_config_t led_conf = {};
    led_conf.gpio_num = BREATH_LED_GPIO;
    led_conf.speed_mode = LEDC_LOW_SPEED_MODE;
    led_conf.channel = BREATH_LED_CHANNEL;
    led_conf.intr_type = LEDC_INTR_DISABLE;
    led_conf.timer_sel = BREATH_LED_TIMER;
    led_conf.duty = 0;
    led_conf.hpoint = 0;
    ledc_channel_config(&led_conf);

    ESP_LOGI(TAG, "[BreathLED] 初始化完成 GPIO=%d", BREATH_LED_GPIO);
}

// 呼吸灯任务 - 使用余弦波实现平滑呼吸效果
static void breath_led_task(void *pvParameters)
{
    ESP_LOGI(TAG, "[BreathLED] 呼吸灯任务启动");

    uint32_t max_duty = (1 << LEDC_TIMER_10_BIT) - 1;  // 1023
    int i = 0;
    int direction = 1;  // 1=渐亮, -1=渐暗

    while (1) {
        // 余弦波实现平滑呼吸
        float phase = i * M_PI / 100.0f;
        float duty_ratio = (1.0f - cosf(phase)) / 2.0f;
        uint32_t duty = (uint32_t)(duty_ratio * max_duty);

        ledc_set_duty(LEDC_LOW_SPEED_MODE, BREATH_LED_CHANNEL, duty);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, BREATH_LED_CHANNEL);

        // 递增/递减计数器
        i += direction;
        if (i >= 100) {
            i = 100;
            direction = -1;  // 到达最亮，开始渐暗
        } else if (i <= 0) {
            i = 0;
            direction = 1;   // 到达最暗，开始渐亮
        }

        vTaskDelay(pdMS_TO_TICKS(30));  // 30ms * 200 = 6秒一个完整周期
    }

    vTaskDelete(NULL);
}

// 编码器读取
static void encoder_read(int *l_count, int *r_count)
{
    int raw_l = 0, raw_r = 0;
    pcnt_unit_get_count(g_pcnt_l, &raw_l);
    pcnt_unit_get_count(g_pcnt_r, &raw_r);
    *l_count = raw_l;
    *r_count = raw_r;

    // 边界处理
    if (raw_l >= 32767 || raw_l <= -32768) {
        pcnt_unit_clear_count(g_pcnt_l);
    }
    if (raw_r >= 32767 || raw_r <= -32768) {
        pcnt_unit_clear_count(g_pcnt_r);
    }
}

// 左电机正转
static void motor_l_forward(uint8_t speed)
{
    gpio_set_level(MOTOR_L_IN1, 0);
    gpio_set_level(MOTOR_L_IN2, 1);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_L_CHANNEL, speed);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_L_CHANNEL);
    g_motor_l_pwm = speed;
}

// 右电机正转
static void motor_r_forward(uint8_t speed)
{
    gpio_set_level(MOTOR_R_IN1, 0);
    gpio_set_level(MOTOR_R_IN2, 1);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_R_CHANNEL, speed);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_R_CHANNEL);
    g_motor_r_pwm = speed;
}

// 停止所有电机
static void motor_stop(void)
{
    gpio_set_level(MOTOR_L_IN1, 0);
    gpio_set_level(MOTOR_L_IN2, 0);
    gpio_set_level(MOTOR_R_IN1, 0);
    gpio_set_level(MOTOR_R_IN2, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_L_CHANNEL, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_R_CHANNEL, 0);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL, 0);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_L_CHANNEL);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_R_CHANNEL);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL);
    g_motor_l_pwm = 0;
    g_motor_r_pwm = 0;
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
// ===========================
// 实验模式视频流（推理+叠加图）
// ===========================
// 实验模式TCP发送：[帧号2B][电压1B][左PWM 1B][右PWM 1B][引导线x 1B][图像数据19200B] = 19206字节/帧
static void experiment_stream(int cmd_sock, int img_sock)
{
    ESP_LOGI(TAG, "========== EXPERIMENT(TCP)开始 ==========");
    ESP_LOGI(TAG, "[Exp] 命令通道=%d, 图像通道=%d", cmd_sock, img_sock);

    if (img_sock < 0) {
        ESP_LOGE(TAG, "[Exp] 图像通道无效");
        send(cmd_sock, "IMG_NOT_READY\n", 15, 0);
        return;
    }

    // 叠加图尺寸：160x120 = 19200字节
    const uint32_t overlay_size = OUTPUT_WIDTH * OUTPUT_HEIGHT;  // 19200
    const int header_size = 10; // 帧号2 + 电压1 + 左PWM1 + 右PWM1 + G11 + G21 + 左跳变率1 + 右跳变率1 + 电机运行态1
    const int frame_packet_size = header_size + overlay_size;   // 19210 字节
    
    // 分配临时缓冲区
    uint8_t *pred_data = (uint8_t *)malloc(INPUT_WIDTH * INPUT_HEIGHT);
    uint8_t *overlay_data = (uint8_t *)malloc(overlay_size);
    
    if (!pred_data || !overlay_data) {
        ESP_LOGE(TAG, "[Exp] 内存分配失败");
        if (pred_data) free(pred_data);
        if (overlay_data) free(overlay_data);
        return;
    }
    
    ESP_LOGI(TAG, "[Exp] TCP图像流: %dx%d=%luB + 头%dB = 每帧%luB", 
             OUTPUT_WIDTH, OUTPUT_HEIGHT, (unsigned long)overlay_size, header_size, (unsigned long)frame_packet_size);
    ESP_LOGI(TAG, "===================================");
    
    int frame_count = 0;
    char cmd_buf[64];
    
    // 重置 PID 状态
    g_smoothed_error = 0.0f;
    g_line_lost_count = 0;
    float g_last_valid_g1 = OUTPUT_WIDTH / 2;
    float g_last_valid_g2 = OUTPUT_WIDTH / 2;

    // 编码器碰撞检测：移动平均比值法
    static int prev_enc_l = 0, prev_enc_r = 0;       // 上一帧累计脉冲值
    static bool enc_init_done = false;
    
    // 移动平均窗口参数
    static const int MA_WINDOW = 10;                   // 滑动窗口大小（帧）
    static int delta_hist_l[10] = {0}, delta_hist_r[10] = {0};
    static int ma_idx = 0;                             // 环形写入位置
    static int ma_count = 0;                           // 已填充帧数
    static const float MA_DROP_RATIO = 0.85f;          // 当前delta低于均值85%即可触发
    
    while (1) {
        int64_t t0 = esp_timer_get_time();  // 总开始
        
        // ========== 图像采集 ==========
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE(TAG, "[Exp] 帧%d: 采集失败", frame_count);
            continue;
        }
        
        // 旋转180度
        rotate_180_inplace(fb->buf, OUTPUT_WIDTH, OUTPUT_HEIGHT);
        
        int64_t t1 = esp_timer_get_time();  // 采集结束

        // ========== 图像预处理（量化查表） ==========
        dl::TensorBase *input_tensor = g_model->get_input("input");
        int8_t *model_input = (int8_t *)input_tensor->data;

        for (int i = 0; i < INPUT_WIDTH * INPUT_HEIGHT; i++) {
            model_input[i] = input_quant_lut[fb->buf[i]];
        }
        int64_t t2 = esp_timer_get_time();  // 预处理结束

        // ========== 模型推理 ==========
        g_model->run();
        dl::TensorBase *output_tensor = g_model->get_output("output");
        int8_t *output_data = (int8_t *)output_tensor->data;
        int64_t t3 = esp_timer_get_time();  // 推理结束
        
        // ========== 后处理：sigmoid查表二值化 ==========
        for (int i = 0; i < OUTPUT_WIDTH * OUTPUT_HEIGHT; i++) {
            uint8_t idx = (uint8_t)(output_data[i] + 128);
            pred_data[i] = sigmoid_lut[idx];
        }
        int64_t t4 = esp_timer_get_time();  // 后处理结束
        
        // ========== 叠加：预测线区域(白色) → 亮显在原图上 ==========
        for (int i = 0; i < OUTPUT_WIDTH * OUTPUT_HEIGHT; i++) {
            if (pred_data[i] == 255) {
                overlay_data[i] = 200;  // 亮灰：预测线区域
            } else {
                overlay_data[i] = fb->buf[i];  // 暗区：原图灰度
            }
        }
        int64_t t5 = esp_timer_get_time();  // 叠加结束
        
        esp_camera_fb_return(fb);

        // ========== 编码器碰撞检测：移动平均比值法 ==========
        int log_ratio_l = 0, log_ratio_r = 0;  // 供外层send_buf使用
        {
            int enc_l = 0, enc_r = 0;
            encoder_read(&enc_l, &enc_r);

            const char *enc_state = "OK";

            if (!enc_init_done) {
                enc_init_done = true;
                enc_state = "INIT";
            } else {
                // 计算本帧增量
                int cur_delta_l = enc_l - prev_enc_l;
                int cur_delta_r = enc_r - prev_enc_r;

                // 溢出检测：ESP32编码器每32768清零，重置历史窗口
                bool overflow_l = (enc_l < 100 && prev_enc_l > 30000);
                bool overflow_r = (enc_r < 100 && prev_enc_r > 30000);

                if (overflow_l || overflow_r) {
                    enc_state = "OVERFLOW";
                    ma_idx = 0;
                    ma_count = 0;
                } else {
                    // 写入滑动窗口
                    delta_hist_l[ma_idx] = cur_delta_l;
                    delta_hist_r[ma_idx] = cur_delta_r;
                    ma_idx = (ma_idx + 1) % MA_WINDOW;
                    if (ma_count < MA_WINDOW) ma_count++;

                    // 计算移动平均
                    int sum_l = 0, sum_r = 0;
                    for (int i = 0; i < MA_WINDOW; i++) {
                        sum_l += delta_hist_l[i];
                        sum_r += delta_hist_r[i];
                    }
                    float avg_l = (float)sum_l / MA_WINDOW;
                    float avg_r = (float)sum_r / MA_WINDOW;

                    // 本帧delta占均值的百分比
                    int ratio_l = (avg_l > 0) ? (int)(cur_delta_l / avg_l * 100) : 100;
                    int ratio_r = (avg_r > 0) ? (int)(cur_delta_r / avg_r * 100) : 100;
                    log_ratio_l = ratio_l;
                    log_ratio_r = ratio_r;

                    // 触发条件：窗口已满 + 累积脉冲>2000 + 左右轮delta同时低于阈值
                    bool enc_moving = (abs(enc_l) > 2000 && abs(enc_r) > 2000);
                    int thr_percent = (int)(MA_DROP_RATIO * 100);
                    if (ma_count >= MA_WINDOW && enc_moving && (ratio_l < thr_percent && ratio_r < thr_percent)) {
                        motor_stop();
                        g_motor_base_speed = 0;
                        g_motor_running = false;
                        enc_state = "TRIGGER";
                    } else {
                        enc_state = "OK";
                    }
                }
            }

            // 每帧统一打印编码器状态
            char enc_log_buf[160];
            int enc_log_len = SNPRINTF_LEN(snprintf(enc_log_buf, sizeof(enc_log_buf),
                "[Enc] %-7s | cur L=%5d R=%5d | delta L=%5d R=%5d | ratio L=%3d%% R=%3d%% (thr=%d%%) | running=%d",
                enc_state, enc_l, enc_r,
                enc_l - prev_enc_l, enc_r - prev_enc_r,
                log_ratio_l, log_ratio_r,
                (int)(MA_DROP_RATIO * 100), (int)g_motor_running), sizeof(enc_log_buf));
            ESP_LOGI(TAG, "%s", enc_log_buf);
            // 直接在有效长度末尾写换行，不用 strcat（strcat 会向缓冲区外多写 1 字节）
            enc_log_buf[enc_log_len] = '\n';
            send(cmd_sock, enc_log_buf, enc_log_len + 1, 0);

            // 更新上一帧累计值
            prev_enc_l = enc_l;
            prev_enc_r = enc_r;
        }

        // ========== PID控制：基于G1/G2质心偏差 ==========
        static const int MAX_LOST_FRAMES = 5;  // 连续丢线超过5帧则停车
        int g0 = OUTPUT_WIDTH / 2;  // 图像中点x = 80
        float g1 = -1, g2 = -1;
        bool line_ok = calc_centroids(pred_data, OUTPUT_WIDTH, OUTPUT_HEIGHT, &g1, &g2);

        if (line_ok) {
            g_line_lost_count = 0;
            g_last_valid_g1 = g1;
            g_last_valid_g2 = g2;
        } else {
            g_line_lost_count++;
            g1 = g_last_valid_g1;
            g2 = g_last_valid_g2;
        }

        if (g_line_lost_count >= MAX_LOST_FRAMES) {
            //ESP_LOGW(TAG, "[PID] 连续丢线%d帧，紧急停车！", g_line_lost_count);
            motor_stop();
        } else if (g_motor_running && g_motor_base_speed > 0) {
            int delta_pwm;
            bool turn_right;
            pid_compute(g1, g2, g0, &delta_pwm, &turn_right);

            int left_pwm, right_pwm;
            if (turn_right) {
                // 右转：左轮加速，右轮减速
                left_pwm = g_motor_base_speed + delta_pwm;
                right_pwm = g_motor_base_speed - delta_pwm;
            } else {
                // 左转：左轮减速，右轮加速
                left_pwm = g_motor_base_speed - delta_pwm;
                right_pwm = g_motor_base_speed + delta_pwm;
            }
            if (left_pwm < 0) left_pwm = 0;
            if (left_pwm > 255) left_pwm = 255;
            if (right_pwm < 0) right_pwm = 0;
            if (right_pwm > 255) right_pwm = 255;
            motor_l_forward(left_pwm);
            motor_r_forward(right_pwm);

            //ESP_LOGI(TAG, "[PID] PWM输出: base=%d delta=%d %s → L=%d R=%d",
            //         g_motor_base_speed, delta_pwm, turn_right ? "RIGHT" : "LEFT", left_pwm, right_pwm);
        } else {
            //ESP_LOGW(TAG, "[PID] 跳过: running=%d base_speed=%d", (int)g_motor_running, g_motor_base_speed);
        }
        
        int64_t t_pid = esp_timer_get_time();  // PID结束

        // ========== TCP发送完整帧 ==========
        // [帧号2B][电压1B][左PWM 1B][右PWM 1B][G1 1B][G2 1B][左跳变率1][右跳变率1][电机运行1B][图像数据19200B] = 19210字节
        uint8_t *send_buf = (uint8_t *)malloc(frame_packet_size);
        int sent_ok = 0;

        if (send_buf) {
            send_buf[0] = (frame_count >> 8) & 0xFF;
            send_buf[1] = frame_count & 0xFF;
            send_buf[2] = battery_read_voltage();
            send_buf[3] = g_motor_l_pwm;
            send_buf[4] = g_motor_r_pwm;
            send_buf[5] = (uint8_t)g1;   // G1: 顶部质心x
            send_buf[6] = (uint8_t)g2;   // G2: 底部质心x
            send_buf[7] = (uint8_t)(log_ratio_l > 255 ? 255 : log_ratio_l);  // 左轮delta占比(%)
            send_buf[8] = (uint8_t)(log_ratio_r > 255 ? 255 : log_ratio_r);  // 右轮delta占比(%)
            send_buf[9] = (uint8_t)g_motor_running;                          // 电机实际运行状态
            memcpy(send_buf + header_size, overlay_data, overlay_size);

            int total_sent = send(img_sock, send_buf, frame_packet_size, 0);
            if (total_sent == frame_packet_size) {
                sent_ok = 1;
            }
            free(send_buf);
        }

        int64_t t6 = esp_timer_get_time();  // 传输结束
        
        // 各阶段耗时(微秒→毫秒)
        float cap_ms = (t1 - t0) / 1000.0f;
        float pre_ms = (t2 - t1) / 1000.0f;
        float infer_ms = (t3 - t2) / 1000.0f;
        float post_ms = (t4 - t3) / 1000.0f;
        float overlay_ms = (t5 - t4) / 1000.0f;
        float pid_ms = (t_pid - t5) / 1000.0f;
        float send_ms = (t6 - t_pid) / 1000.0f;
        float total_ms = (t6 - t0) / 1000.0f;
        
        if (sent_ok) {
            frame_count++;
            if (frame_count % 100 == 0) {
                ESP_LOGI(TAG, "[Exp] 帧%04d | 采%.0f 预%.0f 推%.0f 后%.0f 叠%.0f | 控%.0f 传%.0f | 总%.0fms | G1=%.0f G2=%.0f | 线%s",
                         frame_count,
                         cap_ms, pre_ms, infer_ms, post_ms, overlay_ms,
                         pid_ms, send_ms,
                         total_ms,
                         g1, g2,
                         line_ok ? "OK" : "LOST");
            }
        } else {
            ESP_LOGW(TAG, "[Exp] 帧%04d | TCP发送失败!", frame_count);
        }

        // 非阻塞检查命令
        int len = recv(cmd_sock, cmd_buf, sizeof(cmd_buf) - 1, MSG_DONTWAIT);
        if (len > 0) {
            cmd_buf[len] = '\0';
            ESP_LOGI(TAG, "[Exp] 收到命令: %s", cmd_buf);
            
            if (strncmp(cmd_buf, "STOP_EXPERIMENT", 15) == 0) {
                motor_stop();
                g_motor_base_speed = 0;
                g_motor_running = false;
                ESP_LOGI(TAG, "[Exp] 收到STOP_EXPERIMENT，停止实验模式");
                ESP_LOGI(TAG, "[Exp] 累计帧数: %d", frame_count);
                ESP_LOGI(TAG, "===================================");
                free(pred_data);
                free(overlay_data);
                return;
            }
            else if (strncmp(cmd_buf, "START:", 6) == 0) {
                int speed = atoi(cmd_buf + 6);
                if (speed >= 1 && speed <= 100) {
                    g_motor_running = true;
                    g_motor_base_speed = speed * 255 / 100;
                    motor_l_forward(g_motor_base_speed);
                    motor_r_forward(g_motor_base_speed);
                    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL, MOTOR3_INIT_DUTY);
                    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL);
                    ESP_LOGI(TAG, "[Exp] 启动速度%d%%, PWM=%d, Motor3=%d", speed, g_motor_base_speed, MOTOR3_INIT_DUTY);
                }
            }
            else if (strncmp(cmd_buf, "STOP", 4) == 0) {
                motor_stop();
                g_motor_base_speed = 0;
                g_motor_running = false;
                ESP_LOGI(TAG, "[Exp] 电机停止");
            }
            else if (strncmp(cmd_buf, "SPEED:", 6) == 0) {
                if (!g_motor_running) continue;
                int speed = atoi(cmd_buf + 6);
                if (speed >= 1 && speed <= 100) {
                    g_motor_base_speed = speed * 255 / 100;
                    motor_l_forward(g_motor_base_speed);
                    motor_r_forward(g_motor_base_speed);
                }
            }
            else if (strncmp(cmd_buf, "KP:", 3) == 0) {
                float kp = atof(cmd_buf + 3);
                if (kp >= 0.0f && kp <= 5.0f) {
                    g_pid_kp = kp;
                    ESP_LOGI(TAG, "[Exp] PID比例系数Kp=%.2f", g_pid_kp);
                }
            }
            else if (strncmp(cmd_buf, "MOTOR3:", 7) == 0) {
                int duty = atoi(cmd_buf + 7);
                if (duty >= 0 && duty <= 255) {
                    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL, duty);
                    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL);
                    ESP_LOGI(TAG, "[Exp] 3号电机 PWM=%d (%.0f%%)", duty, duty * 100.0f / 255);
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

// ===========================
// OTA 固件升级处理
// ===========================
#define OTA_BUF_SIZE        4096
#define OTA_ACK_INTERVAL    16384   // 每收满16KB回一次ACK, 供发送端限流与判活

static void ota_handle(int sock, int fw_size)
{
    const esp_partition_t *partition = esp_ota_get_next_update_partition(NULL);
    if (!partition) {
        ESP_LOGE(TAG, "[OTA] 无可用OTA分区");
        send(sock, "OTA_FAIL:no_ota_partition\n", 26, 0);
        return;
    }

    // 必须校验大小: 超限会写坏分区, 过小/为0说明命令解析异常
    if (fw_size <= 0 || (size_t)fw_size > partition->size) {
        ESP_LOGE(TAG, "[OTA] 固件大小非法: %d (分区容量=%u)", fw_size, (unsigned)partition->size);
        send(sock, "OTA_FAIL:bad_size\n", 18, 0);
        return;
    }

    esp_ota_handle_t ota_handle;
    esp_err_t err = esp_ota_begin(partition, fw_size, &ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "[OTA] esp_ota_begin失败: %d", err);
        char msg[64];
        int len = SNPRINTF_LEN(snprintf(msg, sizeof(msg), "OTA_FAIL:begin_err_%d\n", err), sizeof(msg));
        send(sock, msg, len, 0);
        return;
    }

    ESP_LOGI(TAG, "[OTA] 准备就绪, 分区=%s, 固件大小=%d", partition->label, fw_size);
    send(sock, "OTA_READY\n", 10, 0);

    uint8_t *buf = (uint8_t *)malloc(OTA_BUF_SIZE);
    if (!buf) {
        ESP_LOGE(TAG, "[OTA] 内存不足, 无法分配接收缓冲");
        esp_ota_abort(ota_handle);
        send(sock, "OTA_FAIL:nomem\n", 15, 0);
        return;
    }
    int total = 0;
    int last_pct = -1;
    int since_ack = 0;

    while (total < fw_size) {
        int to_read = fw_size - total;
        if (to_read > OTA_BUF_SIZE) to_read = OTA_BUF_SIZE;

        int len = recv(sock, buf, to_read, 0);
        if (len <= 0) {
            ESP_LOGE(TAG, "[OTA] 接收失败 已收=%d/%d", total, fw_size);
            free(buf);
            esp_ota_abort(ota_handle);   // 出错必须abort, 不能end, 否则分区处于中间态
            send(sock, "OTA_FAIL:recv_error\n", 20, 0);
            return;
        }

        err = esp_ota_write(ota_handle, buf, len);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "[OTA] 写入失败: %d", err);
            free(buf);
            esp_ota_abort(ota_handle);
            send(sock, "OTA_FAIL:write_error\n", 21, 0);
            return;
        }

        total += len;
        since_ack += len;

        int pct = total * 100 / fw_size;
        int report_pct = (pct / 10) * 10;
        if (report_pct != last_pct) {
            last_pct = report_pct;
            char pct_msg[32];
            int pct_len = SNPRINTF_LEN(snprintf(pct_msg, sizeof(pct_msg), "OTA_PROGRESS:%d\n", report_pct), sizeof(pct_msg));
            send(sock, pct_msg, pct_len, 0);
            ESP_LOGI(TAG, "[OTA] 进度: %d%%", report_pct);
        }

        // 回执: 让发送端确认设备仍在正常写入, 避免发送端盲发
        if (since_ack >= OTA_ACK_INTERVAL || total >= fw_size) {
            since_ack = 0;
            char ack_msg[32];
            int ack_len = SNPRINTF_LEN(snprintf(ack_msg, sizeof(ack_msg), "OTA_ACK:%d\n", total), sizeof(ack_msg));
            send(sock, ack_msg, ack_len, 0);
        }
    }

    free(buf);

    err = esp_ota_end(ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "[OTA] esp_ota_end失败: %d", err);
        esp_ota_abort(ota_handle);
        send(sock, "OTA_FAIL:end_error\n", 19, 0);
        return;
    }

    err = esp_ota_set_boot_partition(partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "[OTA] 设置启动分区失败: %d", err);
        send(sock, "OTA_FAIL:boot_set_error\n", 24, 0);
        return;
    }

    ESP_LOGI(TAG, "[OTA] 完成! 总计=%d字节, 准备重启", total);
    send(sock, "OTA_OK\n", 7, 0);

    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}

static void handle_client(int client_sock, int server_sock)
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
        char cmd[128] = {};
        int ci = 0;
        while (ci < (int)sizeof(cmd) - 1) {
            int r = recv(client_sock, cmd + ci, 1, 0);
            if (r <= 0) {
                if (ci == 0) {
                    ESP_LOGI(TAG, "[TCP] 客户端断开");
                    goto client_disconnected;
                }
                // 收到部分数据但recv失败, 等待50ms重试
                vTaskDelay(pdMS_TO_TICKS(50));
                continue;
            }
            if (cmd[ci] == '\n') break;
            ci++;
        }
        cmd[ci] = '\0';

        ESP_LOGI(TAG, "[TCP] 收到命令: %s", cmd);

        if (strncmp(cmd, "START:", 6) == 0) {
            int speed = atoi(cmd + 6);
            if (speed >= 1 && speed <= 100) {
                g_motor_running = true;
                g_motor_base_speed = speed * 255 / 100;
                motor_l_forward(g_motor_base_speed);
                motor_r_forward(g_motor_base_speed);
                ledc_set_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL, MOTOR3_INIT_DUTY);
                ledc_update_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL);
                ESP_LOGI(TAG, "[Motor] 启动速度%d%%, PWM=%d, Motor3=%d", speed, g_motor_base_speed, MOTOR3_INIT_DUTY);
            }
        }
        else if (strncmp(cmd, "SPEED:", 6) == 0) {
            if (!g_motor_running) {
                ESP_LOGI(TAG, "[Motor] 电机未启动，忽略SPEED命令");
                continue;
            }
            int speed = atoi(cmd + 6);
            if (speed >= 1 && speed <= 100) {
                g_motor_base_speed = speed * 255 / 100;
                motor_l_forward(g_motor_base_speed);
                motor_r_forward(g_motor_base_speed);
                ESP_LOGI(TAG, "[Motor] 速度设置为%d%%, PWM=%d", speed, g_motor_base_speed);
            }
        }
        else if (strncmp(cmd, "MOTOR_LEFT", 10) == 0) {
            if (!g_motor_running) continue;
            motor_r_forward(g_motor_base_speed);
            motor_l_forward(g_motor_base_speed / 2);
            ESP_LOGI(TAG, "[Motor] 左转: L=%d, R=%d", g_motor_base_speed / 2, g_motor_base_speed);
        }
        else if (strncmp(cmd, "MOTOR_RIGHT", 11) == 0) {
            if (!g_motor_running) continue;
            motor_l_forward(g_motor_base_speed);
            motor_r_forward(g_motor_base_speed / 2);
            ESP_LOGI(TAG, "[Motor] 右转: L=%d, R=%d", g_motor_base_speed, g_motor_base_speed / 2);
        }
        else if (strncmp(cmd, "MOTOR_FORWARD", 13) == 0) {
            if (!g_motor_running) continue;
            motor_l_forward(g_motor_base_speed);
            motor_r_forward(g_motor_base_speed);
            ESP_LOGI(TAG, "[Motor] 直行: L=%d, R=%d", g_motor_base_speed, g_motor_base_speed);
        }
        else if (strncmp(cmd, "STOP", 4) == 0 && (cmd[4] == '\0' || cmd[4] == '\n' || cmd[4] == '\r')) {
            motor_stop();
            g_motor_base_speed = 0;
            g_motor_running = false;
            ESP_LOGI(TAG, "[Motor] 收到STOP命令，电机已停止");
        }
        else if (strncmp(cmd, "CAPTURE", 7) == 0) {
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

            // 获取模型输入tensor和量化参数
            dl::TensorBase *input_tensor = g_model->get_input("input");
            std::vector<int> in_shape = input_tensor->get_shape();
            ESP_LOGI(TAG, "[Input] Tensor shape: %d x %d x %d x %d",
                     in_shape.size() > 0 ? in_shape[0] : 0,
                     in_shape.size() > 1 ? in_shape[1] : 0,
                     in_shape.size() > 2 ? in_shape[2] : 0,
                     in_shape.size() > 3 ? in_shape[3] : 0);

            int8_t *model_input = (int8_t *)input_tensor->data;

            // 归一化并量化: uint8 [0,255] -> int8，查表代替逐像素浮点运算
            for (int i = 0; i < INPUT_WIDTH * INPUT_HEIGHT; i++) {
                model_input[i] = input_quant_lut[fb->buf[i]];
            }

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
            free(concat_data);
            
            esp_camera_fb_return(fb);
        }
        else if (strncmp(cmd, "UDP_HELLO", 9) == 0) {
            // 解析客户端UDP端口: UDP_HELLO:端口
            int client_udp_port = 0;
            char *port_str = strchr(cmd, ':');
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
        else if (strncmp(cmd, "STREAM", 6) == 0) {
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
                    
                    // 第一分片包含电机PWM值
                    uint8_t *chunk_buf;
                    int header_size;
                    
                    if (i == 0) {
                        // 第一分片：[帧号2B][总分片1B][索引1B][电压1B][左电机PWM 1B][右电机PWM 1B][编码器L 2B][编码器R 2B][数据...]
                        int enc_l = 0, enc_r = 0;
                        encoder_read(&enc_l, &enc_r);
                        uint8_t bat_voltage = battery_read_voltage();
                        chunk_buf = (uint8_t *)malloc(11 + current_chunk_size);
                        header_size = 11;
                        chunk_buf[4] = bat_voltage;   // 电池电压(十分之一伏特)
                        chunk_buf[5] = g_motor_l_pwm;  // 左电机PWM值
                        chunk_buf[6] = g_motor_r_pwm;  // 右电机PWM值
                        chunk_buf[7] = (enc_l >> 8) & 0xFF;  // 左编码器 高字节
                        chunk_buf[8] = enc_l & 0xFF;          // 左编码器 低字节
                        chunk_buf[9] = (enc_r >> 8) & 0xFF;  // 右编码器 高字节
                        chunk_buf[10] = enc_r & 0xFF;         // 右编码器 低字节
                    } else {
                        // 其他分片：[帧号2B][总分片1B][索引1B][数据...]
                        chunk_buf = (uint8_t *)malloc(4 + current_chunk_size);
                        header_size = 4;
                    }
                    
                    if (chunk_buf) {
                        // 协议头
                        chunk_buf[0] = (frame_count >> 8) & 0xFF;    // 帧号高字节
                        chunk_buf[1] = frame_count & 0xFF;           // 帧号低字节
                        chunk_buf[2] = total_chunks;                  // 总分片数
                        chunk_buf[3] = i;                             // 当前分片索引
                        
                        // 复制数据
                        memcpy(chunk_buf + header_size, fb->buf + offset, current_chunk_size);
                        
                        // 发送UDP分片
                        int sent = sendto(g_udp_sock, chunk_buf, header_size + current_chunk_size, 0,
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
                    // 每20帧打印一次编码器值
                    int l_count = 0, r_count = 0;
                    encoder_read(&l_count, &r_count);
                    if (frame_count % 20 == 0) {
                        ESP_LOGI(TAG, "[Encoder] 左轮:%d  右轮:%d", l_count, r_count);
                    }
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
                        if (speed >= 1 && speed <= 100) {
                            g_motor_running = true;
                            g_motor_base_speed = speed * 255 / 100;
                            motor_l_forward(g_motor_base_speed);
                            motor_r_forward(g_motor_base_speed);
                            ledc_set_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL, MOTOR3_INIT_DUTY);
                            ledc_update_duty(MOTOR_LEDC_MODE, MOTOR3_CHANNEL);
                            ESP_LOGI(TAG, "[Motor] 启动速度%d%%, PWM=%d, Motor3=%d", speed, g_motor_base_speed, MOTOR3_INIT_DUTY);
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
                        if (speed >= 1 && speed <= 100) {
                            g_motor_base_speed = speed * 255 / 100;
                            motor_l_forward(g_motor_base_speed);
                            motor_r_forward(g_motor_base_speed);
                            ESP_LOGI(TAG, "[Motor] 速度设置为%d%%, PWM=%d", speed, g_motor_base_speed);
                        }
                    }
                    else if (strncmp(buf, "MOTOR_LEFT", 10) == 0) {
                        if (!g_motor_running) continue;
                        motor_r_forward(g_motor_base_speed);
                        motor_l_forward(g_motor_base_speed / 2);
                        ESP_LOGI(TAG, "[Motor] 左转: L=%d, R=%d", g_motor_base_speed / 2, g_motor_base_speed);
                    }
                    else if (strncmp(buf, "MOTOR_RIGHT", 11) == 0) {
                        if (!g_motor_running) continue;
                        motor_l_forward(g_motor_base_speed);
                        motor_r_forward(g_motor_base_speed / 2);
                        ESP_LOGI(TAG, "[Motor] 右转: L=%d, R=%d", g_motor_base_speed, g_motor_base_speed / 2);
                    }
                    else if (strncmp(buf, "MOTOR_FORWARD", 13) == 0) {
                        if (!g_motor_running) continue;
                        motor_l_forward(g_motor_base_speed);
                        motor_r_forward(g_motor_base_speed);
                        ESP_LOGI(TAG, "[Motor] 直行: L=%d, R=%d", g_motor_base_speed, g_motor_base_speed);
                    }
                }

                // 小延时，控制帧率
                vTaskDelay(pdMS_TO_TICKS(20));
            }
        }
        else if (strncmp(cmd, "EXPERIMENT", 10) == 0) {
            // 等待小程序建立第二条图像TCP连接
            ESP_LOGI(TAG, "[Exp] 等待图像通道连接...");
            send(client_sock, "WAITING_IMG_CONN\n", 17, 0);

            struct sockaddr_in img_addr;
            socklen_t img_addr_len = sizeof(img_addr);
            int img_sock = accept(server_sock, (struct sockaddr *)&img_addr, &img_addr_len);

            if (img_sock >= 0) {
                // 读取图像通道握手
                char img_handshake[32] = {};
                int img_hs_len = recv(img_sock, img_handshake, sizeof(img_handshake) - 1, 0);
                if (img_hs_len > 0) {
                    img_handshake[img_hs_len] = '\0';
                    ESP_LOGI(TAG, "[Exp] 图像通道握手: %s", img_handshake);
                    send(img_sock, "IMG_OK\n", 7, 0);
                }

                ESP_LOGI(TAG, "[Exp] 图像通道已连接(sock=%d), 开始实验模式", img_sock);
                experiment_stream(client_sock, img_sock);

                close(img_sock);
                ESP_LOGI(TAG, "[Exp] 图像通道已关闭");
            } else {
                ESP_LOGE(TAG, "[Exp] 图像通道accept失败");
                send(client_sock, "IMG_CONN_FAILED\n", 17, 0);
            }
        }
        else if (strncmp(cmd, "OTA:START:", 10) == 0) {
            char *filename = cmd + 10;
            char *size_str = strchr(filename, ':');
            if (!size_str) {
                ESP_LOGE(TAG, "[OTA] 命令格式错误, 缺少大小字段");
                send(client_sock, "OTA_FAIL:bad_cmd\n", 17, 0);
                continue;
            }
            *size_str = '\0';
            // 严格解析大小: 非数字/<=0 直接拒绝, 不让 atoi 的 0 蒙混过关
            char *endptr = NULL;
            long fw_size = strtol(size_str + 1, &endptr, 10);
            if (endptr == size_str + 1 || fw_size <= 0 || fw_size > 0x7FFFFFFFL) {
                ESP_LOGE(TAG, "[OTA] 固件大小字段非法: %s", size_str + 1);
                send(client_sock, "OTA_FAIL:bad_size\n", 18, 0);
                continue;
            }
            ESP_LOGI(TAG, "[OTA] 收到OTA:START 文件=%s 大小=%ld", filename, fw_size);
            ota_handle(client_sock, (int)fw_size);
        }
    }

client_disconnected:
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
    listen(server_sock, 2);  // 支持命令+图像两条连接

    ESP_LOGI(TAG, "[TCP] Server已启动, 端口=%d", TCP_PORT);

    while (1) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);
        int client_sock = accept(server_sock, (struct sockaddr *)&client_addr, &addr_len);

        if (client_sock >= 0) {
            handle_client(client_sock, server_sock);
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

    // 根据模型输出量化参数初始化sigmoid查表
    dl::TensorBase *out_tensor = g_model->get_output("output");
    int out_exponent = out_tensor->get_exponent();
    float out_scale = DL_SCALE(out_exponent);
    init_sigmoid_lut(out_scale);
    ESP_LOGI(TAG, "[Init] Sigmoid查表初始化完成 (exponent=%d, scale=%.6f)", out_exponent, out_scale);

    // 根据模型输入量化参数初始化输入量化查表
    float in_inv_scale = DL_RESCALE(g_model->get_input("input")->get_exponent());
    init_input_quant_lut(in_inv_scale);
    ESP_LOGI(TAG, "[Init] 输入量化查表初始化完成 (inv_scale=%.6f)", in_inv_scale);

    camera_init();
    motor_init();
    encoder_init();
    wifi_init_ap();
    udp_init();

    // ADC初始化放最后，避免影响摄像头GPIO
    battery_adc_init();

    // 已成功跑到主逻辑: 标记当前固件有效, 取消回滚
    // 配合 CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE, OTA 后起不来会自动回滚到旧固件
    esp_ota_mark_app_valid_cancel_rollback();

    // 呼吸灯初始化（所有功能初始化完成后开始）
    breath_led_init();
    xTaskCreate(breath_led_task, "breath_led", 4096, NULL, 2, NULL);

    // TCP服务器任务绑定到Core 1，推理任务与WiFi底层(Core 0)分离
    xTaskCreatePinnedToCore(tcp_server_task, "tcp_server", 16384, NULL, 5, NULL, 1);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "系统启动完成!");
    ESP_LOGI(TAG, "热点: %s  密码: %s", AP_SSID, AP_PASSWORD);
    ESP_LOGI(TAG, "TCP端口: %d  UDP端口: %d", TCP_PORT, UDP_PORT);
    ESP_LOGI(TAG, "呼吸灯: GPIO%d", BREATH_LED_GPIO);
    ESP_LOGI(TAG, "========================================");


}