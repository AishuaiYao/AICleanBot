#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "driver/pulse_cnt.h"

static const char *TAG = "ENC_TEST";

// 引脚定义
#define MOTOR_A_PWM   GPIO_NUM_1
#define MOTOR_A_IN1   GPIO_NUM_2
#define MOTOR_A_IN2   GPIO_NUM_42
#define MOTOR_B_PWM   GPIO_NUM_41
#define MOTOR_B_IN1   GPIO_NUM_40
#define MOTOR_B_IN2   GPIO_NUM_39
#define ENCODER_L_A   GPIO_NUM_38
#define ENCODER_L_B   GPIO_NUM_47
#define ENCODER_R_A   GPIO_NUM_21
#define ENCODER_R_B   GPIO_NUM_14

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

    // 电机A PWM
    ledc_channel_config_t ch_a = {};
    ch_a.gpio_num = MOTOR_A_PWM;
    ch_a.speed_mode = LEDC_LOW_SPEED_MODE;
    ch_a.channel = LEDC_CHANNEL_1;
    ch_a.intr_type = LEDC_INTR_DISABLE;
    ch_a.timer_sel = LEDC_TIMER_1;
    ch_a.duty = 0;
    ledc_channel_config(&ch_a);

    // 电机B PWM
    ledc_channel_config_t ch_b = {};
    ch_b.gpio_num = MOTOR_B_PWM;
    ch_b.speed_mode = LEDC_LOW_SPEED_MODE;
    ch_b.channel = LEDC_CHANNEL_2;
    ch_b.intr_type = LEDC_INTR_DISABLE;
    ch_b.timer_sel = LEDC_TIMER_1;
    ch_b.duty = 0;
    ledc_channel_config(&ch_b);

    // 方向GPIO
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << MOTOR_A_IN1) | (1ULL << MOTOR_A_IN2) |
                           (1ULL << MOTOR_B_IN1) | (1ULL << MOTOR_B_IN2);
    io_conf.mode = GPIO_MODE_OUTPUT;
    gpio_config(&io_conf);

    gpio_set_level(MOTOR_A_IN1, 0);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 0);
    gpio_set_level(MOTOR_B_IN2, 0);
}

// ===========================
// 编码器初始化 - 4个独立PCNT
// ===========================
static void encoder_init(void)
{
    // 配置GPIO上拉
    gpio_config_t pull_conf = {};
    pull_conf.pin_bit_mask = (1ULL << ENCODER_L_A) | (1ULL << ENCODER_L_B) |
                             (1ULL << ENCODER_R_A) | (1ULL << ENCODER_R_B);
    pull_conf.mode = GPIO_MODE_INPUT;
    pull_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    gpio_config(&pull_conf);

    // PCNT单元配置
    pcnt_unit_config_t unit_conf = {};
    unit_conf.high_limit = 32767;
    unit_conf.low_limit = -32768;
    unit_conf.flags.accum_count = 1;

    // 左编码器A相
    pcnt_new_unit(&unit_conf, &g_pcnt_l_a);
    pcnt_chan_config_t chan_a = {};
    chan_a.edge_gpio_num = ENCODER_L_A;
    pcnt_channel_handle_t ch_la = NULL;
    pcnt_new_channel(g_pcnt_l_a, &chan_a, &ch_la);
    pcnt_channel_set_edge_action(ch_la, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 左编码器B相
    pcnt_new_unit(&unit_conf, &g_pcnt_l_b);
    pcnt_chan_config_t chan_b = {};
    chan_b.edge_gpio_num = ENCODER_L_B;
    pcnt_channel_handle_t ch_lb = NULL;
    pcnt_new_channel(g_pcnt_l_b, &chan_b, &ch_lb);
    pcnt_channel_set_edge_action(ch_lb, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 右编码器A相
    pcnt_new_unit(&unit_conf, &g_pcnt_r_a);
    chan_a.edge_gpio_num = ENCODER_R_A;
    pcnt_channel_handle_t ch_ra = NULL;
    pcnt_new_channel(g_pcnt_r_a, &chan_a, &ch_ra);
    pcnt_channel_set_edge_action(ch_ra, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 右编码器B相
    pcnt_new_unit(&unit_conf, &g_pcnt_r_b);
    chan_b.edge_gpio_num = ENCODER_R_B;
    pcnt_channel_handle_t ch_rb = NULL;
    pcnt_new_channel(g_pcnt_r_b, &chan_b, &ch_rb);
    pcnt_channel_set_edge_action(ch_rb, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD);

    // 使能并启动
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

    // 重新启用上拉
    gpio_pullup_en(ENCODER_L_A);
    gpio_pullup_en(ENCODER_L_B);
    gpio_pullup_en(ENCODER_R_A);
    gpio_pullup_en(ENCODER_R_B);
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
    gpio_set_level(MOTOR_A_IN1, 1);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 1);
    gpio_set_level(MOTOR_B_IN2, 0);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 51);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2, 51);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2);

    ESP_LOGI(TAG, "Motor started, 20%% duty");

    while (1) {
        int la_cnt = 0, lb_cnt = 0, ra_cnt = 0, rb_cnt = 0;
        pcnt_unit_get_count(g_pcnt_l_a, &la_cnt);
        pcnt_unit_get_count(g_pcnt_l_b, &lb_cnt);
        pcnt_unit_get_count(g_pcnt_r_a, &ra_cnt);
        pcnt_unit_get_count(g_pcnt_r_b, &rb_cnt);

        int la = gpio_get_level(ENCODER_L_A);
        int lb = gpio_get_level(ENCODER_L_B);
        int ra = gpio_get_level(ENCODER_R_A);
        int rb = gpio_get_level(ENCODER_R_B);

        ESP_LOGI(TAG, "LA=%d LB=%d RA=%d RB=%d | GPIO L(%d,%d) R(%d,%d)", la_cnt, lb_cnt, ra_cnt, rb_cnt, la, lb, ra, rb);

        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
