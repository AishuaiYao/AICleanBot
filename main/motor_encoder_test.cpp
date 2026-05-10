#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "driver/pulse_cnt.h"

static const char *TAG = "ENC_TEST";

// 引脚定义
// 左轮
#define MOTOR_L_PWM   GPIO_NUM_39    // 左轮PWMB（速度控制）
#define MOTOR_L_IN1   GPIO_NUM_45    // 左轮BIN1（方向控制）
#define MOTOR_L_IN2   GPIO_NUM_48    // 左轮BIN2（方向控制）
#define ENCODER_L_A   GPIO_NUM_47    // 左编码器E2A
#define ENCODER_L_B   GPIO_NUM_21    // 左编码器E2B

// 右轮
#define MOTOR_R_PWM   GPIO_NUM_1     // 右轮PWMA（速度控制）
#define MOTOR_R_IN1   GPIO_NUM_2     // 右轮AIN1（方向控制）
#define MOTOR_R_IN2   GPIO_NUM_42    // 右轮AIN2（方向控制）
#define ENCODER_R_A   GPIO_NUM_41    // 右编码器E1A
#define ENCODER_R_B   GPIO_NUM_40    // 右编码器E1B

// PCNT句柄 - 一倍频
static pcnt_unit_handle_t g_pcnt_l = NULL;  // 左编码器
static pcnt_unit_handle_t g_pcnt_r = NULL;  // 右编码器
static bool g_motor_dir = true;  // true=正转, false=反转
static bool g_last_motor_dir = true;  // 上次方向

// ===========================
// 电机初始化
// ===========================
static void motor_init(void)
{
    ledc_timer_config_t timer_conf = {};
    timer_conf.speed_mode = LEDC_LOW_SPEED_MODE;
    timer_conf.duty_resolution = LEDC_TIMER_8_BIT;
    timer_conf.timer_num = LEDC_TIMER_1;
    timer_conf.freq_hz = 1000;
    timer_conf.clk_cfg = LEDC_AUTO_CLK;
    ledc_timer_config(&timer_conf);

    // 左轮PWM
    ledc_channel_config_t ch_l = {};
    ch_l.gpio_num = MOTOR_L_PWM;
    ch_l.speed_mode = LEDC_LOW_SPEED_MODE;
    ch_l.channel = LEDC_CHANNEL_1;
    ch_l.intr_type = LEDC_INTR_DISABLE;
    ch_l.timer_sel = LEDC_TIMER_1;
    ch_l.duty = 0;
    ledc_channel_config(&ch_l);

    // 右轮PWM
    ledc_channel_config_t ch_r = {};
    ch_r.gpio_num = MOTOR_R_PWM;
    ch_r.speed_mode = LEDC_LOW_SPEED_MODE;
    ch_r.channel = LEDC_CHANNEL_2;
    ch_r.intr_type = LEDC_INTR_DISABLE;
    ch_r.timer_sel = LEDC_TIMER_1;
    ch_r.duty = 0;
    ledc_channel_config(&ch_r);

    // 方向GPIO配置
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << MOTOR_L_IN1) | (1ULL << MOTOR_L_IN2) |
                           (1ULL << MOTOR_R_IN1) | (1ULL << MOTOR_R_IN2);
    io_conf.mode = GPIO_MODE_OUTPUT;
    gpio_config(&io_conf);
}

// ===========================
// 设置电机方向（反转时清零计数器）
// ===========================
static void set_motor_direction(bool forward)
{
    if (forward != g_last_motor_dir) {
        // 方向变化，清零计数器
        pcnt_unit_clear_count(g_pcnt_l);
        pcnt_unit_clear_count(g_pcnt_r);
        g_last_motor_dir = forward;
    }
    
    if (forward) {
        gpio_set_level(MOTOR_L_IN1, 0);
        gpio_set_level(MOTOR_L_IN2, 1);
        gpio_set_level(MOTOR_R_IN1, 0);
        gpio_set_level(MOTOR_R_IN2, 1);
        ESP_LOGI(TAG, ">>> 方向: 正转");
    } else {
        gpio_set_level(MOTOR_L_IN1, 1);
        gpio_set_level(MOTOR_L_IN2, 0);
        gpio_set_level(MOTOR_R_IN1, 1);
        gpio_set_level(MOTOR_R_IN2, 0);
        ESP_LOGI(TAG, ">>> 方向: 反转");
    }
}

// ===========================
// 编码器初始化 - 一倍频（A相上升沿+1）
// ===========================
static void encoder_init(void)
{
    // 配置GPIO
    gpio_config_t pull_conf = {};
    pull_conf.pin_bit_mask = (1ULL << ENCODER_L_A) | (1ULL << ENCODER_L_B) |
                             (1ULL << ENCODER_R_A) | (1ULL << ENCODER_R_B);
    pull_conf.mode = GPIO_MODE_INPUT;
    pull_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    pull_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    gpio_config(&pull_conf);

    // 左编码器 - 简单A相上升沿+1
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

    // 右编码器
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
}

// ===========================
// 读取编码器（根据方向返回正/负值，边界清零）
// ===========================
static void get_encoder_count(int *left, int *right)
{
    int raw_left = 0, raw_right = 0;
    pcnt_unit_get_count(g_pcnt_l, &raw_left);
    pcnt_unit_get_count(g_pcnt_r, &raw_right);
    
    // 根据当前电机方向返回正数或负数
    if (g_last_motor_dir) {
        // 正转，返回正值
        *left = raw_left;
        *right = raw_right;
    } else {
        // 反转，返回负值
        *left = -raw_left;
        *right = -raw_right;
    }
    
    // 边界处理
    if (raw_left >= 32767 || raw_left <= -32768) {
        pcnt_unit_clear_count(g_pcnt_l);
    }
    if (raw_right >= 32767 || raw_right <= -32768) {
        pcnt_unit_clear_count(g_pcnt_r);
    }
}

// ===========================
// 主任务
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "===== Encoder Test =====");

    motor_init();
    encoder_init();

    // 启动电机
    set_motor_direction(g_motor_dir);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 200);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2, 200);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2);

    ESP_LOGI(TAG, "Motor started, testing with 5s direction toggle");

    int tick_count = 0;

    while (1) {
        int left_cnt = 0, right_cnt = 0;
        get_encoder_count(&left_cnt, &right_cnt);

        ESP_LOGI(TAG, "Left=%d Right=%d", left_cnt, right_cnt);

        vTaskDelay(pdMS_TO_TICKS(200));

        // 每5秒反转一次方向 (25 * 200ms = 5s)
        tick_count++;
        if (tick_count >= 25) {
            tick_count = 0;
            g_motor_dir = !g_motor_dir;
            set_motor_direction(g_motor_dir);
            // 不清零，让正负数继续累积
        }
    }
}
