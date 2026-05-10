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

// PCNT句柄 - 4个独立计数器
static pcnt_unit_handle_t g_pcnt_l_a = NULL;
static pcnt_unit_handle_t g_pcnt_l_b = NULL;
static pcnt_unit_handle_t g_pcnt_r_a = NULL;
static pcnt_unit_handle_t g_pcnt_r_b = NULL;

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

    gpio_set_level(MOTOR_L_IN1, 0);
    gpio_set_level(MOTOR_L_IN2, 0);
    gpio_set_level(MOTOR_R_IN1, 0);
    gpio_set_level(MOTOR_R_IN2, 0);
}

// ===========================
// 编码器初始化 - 4个独立PCNT
// ===========================
static void encoder_init(void)
{
    // 配置GPIO（不上拉，由编码器硬件上拉）
    gpio_config_t pull_conf = {};
    pull_conf.pin_bit_mask = (1ULL << ENCODER_L_A) | (1ULL << ENCODER_L_B) |
                             (1ULL << ENCODER_R_A) | (1ULL << ENCODER_R_B);
    pull_conf.mode = GPIO_MODE_INPUT;
    pull_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    pull_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    gpio_config(&pull_conf);

    // PCNT单元配置
    pcnt_unit_config_t unit_conf = {};
    unit_conf.high_limit = 32767;
    unit_conf.low_limit = -32768;
    unit_conf.flags.accum_count = 1;

    // 左编码器A相
    pcnt_new_unit(&unit_conf, &g_pcnt_l_a);
    pcnt_chan_config_t chan_la = {};
    chan_la.edge_gpio_num = ENCODER_L_A;
    pcnt_channel_handle_t ch_la = NULL;
    pcnt_new_channel(g_pcnt_l_a, &chan_la, &ch_la);
    pcnt_channel_set_edge_action(ch_la, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 左编码器B相
    pcnt_new_unit(&unit_conf, &g_pcnt_l_b);
    pcnt_chan_config_t chan_lb = {};
    chan_lb.edge_gpio_num = ENCODER_L_B;
    pcnt_channel_handle_t ch_lb = NULL;
    pcnt_new_channel(g_pcnt_l_b, &chan_lb, &ch_lb);
    pcnt_channel_set_edge_action(ch_lb, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 右编码器A相
    pcnt_new_unit(&unit_conf, &g_pcnt_r_a);
    pcnt_chan_config_t chan_ra = {};
    chan_ra.edge_gpio_num = ENCODER_R_A;
    pcnt_channel_handle_t ch_ra = NULL;
    pcnt_new_channel(g_pcnt_r_a, &chan_ra, &ch_ra);
    pcnt_channel_set_edge_action(ch_ra, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 右编码器B相
    pcnt_new_unit(&unit_conf, &g_pcnt_r_b);
    pcnt_chan_config_t chan_rb = {};
    chan_rb.edge_gpio_num = ENCODER_R_B;
    pcnt_channel_handle_t ch_rb = NULL;
    pcnt_new_channel(g_pcnt_r_b, &chan_rb, &ch_rb);
    pcnt_channel_set_edge_action(ch_rb, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 启动所有PCNT单元
    pcnt_unit_enable(g_pcnt_l_a);
    pcnt_unit_enable(g_pcnt_l_b);
    pcnt_unit_enable(g_pcnt_r_a);
    pcnt_unit_enable(g_pcnt_r_b);
    pcnt_unit_clear_count(g_pcnt_l_a);
    pcnt_unit_clear_count(g_pcnt_l_b);
    pcnt_unit_clear_count(g_pcnt_r_a);
    pcnt_unit_clear_count(g_pcnt_r_b);
    pcnt_unit_start(g_pcnt_l_a);
    pcnt_unit_start(g_pcnt_l_b);
    pcnt_unit_start(g_pcnt_r_a);
    pcnt_unit_start(g_pcnt_r_b);
}

// ===========================
// 主任务
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "===== Encoder Test =====");

    motor_init();
    encoder_init();

    // 启动电机（方向反转）
    gpio_set_level(MOTOR_L_IN1, 0);
    gpio_set_level(MOTOR_L_IN2, 1);
    gpio_set_level(MOTOR_R_IN1, 0);
    gpio_set_level(MOTOR_R_IN2, 1);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 255);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2, 255);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2);

    ESP_LOGI(TAG, "Motor started");

    while (1) {
        int la_cnt = 0, lb_cnt = 0, ra_cnt = 0, rb_cnt = 0;
        pcnt_unit_get_count(g_pcnt_l_a, &la_cnt);
        pcnt_unit_get_count(g_pcnt_l_b, &lb_cnt);
        pcnt_unit_get_count(g_pcnt_r_a, &ra_cnt);
        pcnt_unit_get_count(g_pcnt_r_b, &rb_cnt);

        ESP_LOGI(TAG, "LA=%d LB=%d RA=%d RB=%d", la_cnt, lb_cnt, ra_cnt, rb_cnt);

        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
