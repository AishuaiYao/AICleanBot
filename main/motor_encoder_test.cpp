#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "driver/pulse_cnt.h"

static const char *TAG = "MOTOR_ENC_TEST";

// ===========================
// 引脚定义
// ===========================
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

#define LEDC_TIMER      LEDC_TIMER_1
#define LEDC_MODE       LEDC_LOW_SPEED_MODE
#define LEDC_RESOLUTION LEDC_TIMER_8_BIT
#define LEDC_FREQ       1000

#define MOTOR_A_CHANNEL LEDC_CHANNEL_1
#define MOTOR_B_CHANNEL LEDC_CHANNEL_2

// PCNT 句柄
static pcnt_unit_handle_t g_pcnt_l = NULL;
static pcnt_unit_handle_t g_pcnt_r = NULL;

// ===========================
// 电机初始化
// ===========================
static void motor_init(void)
{
    // LEDC 定时器
    ledc_timer_config_t timer_conf = {};
    timer_conf.speed_mode = LEDC_MODE;
    timer_conf.duty_resolution = LEDC_RESOLUTION;
    timer_conf.timer_num = LEDC_TIMER;
    timer_conf.freq_hz = LEDC_FREQ;
    timer_conf.clk_cfg = LEDC_AUTO_CLK;
    ledc_timer_config(&timer_conf);

    // 电机A PWM
    ledc_channel_config_t ch_a = {};
    ch_a.gpio_num = MOTOR_A_PWM;
    ch_a.speed_mode = LEDC_MODE;
    ch_a.channel = MOTOR_A_CHANNEL;
    ch_a.intr_type = LEDC_INTR_DISABLE;
    ch_a.timer_sel = LEDC_TIMER;
    ch_a.duty = 0;
    ch_a.hpoint = 0;
    ledc_channel_config(&ch_a);

    // 电机B PWM
    ledc_channel_config_t ch_b = {};
    ch_b.gpio_num = MOTOR_B_PWM;
    ch_b.speed_mode = LEDC_MODE;
    ch_b.channel = MOTOR_B_CHANNEL;
    ch_b.intr_type = LEDC_INTR_DISABLE;
    ch_b.timer_sel = LEDC_TIMER;
    ch_b.duty = 0;
    ch_b.hpoint = 0;
    ledc_channel_config(&ch_b);

    // 方向GPIO
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << MOTOR_A_IN1) | (1ULL << MOTOR_A_IN2) |
                           (1ULL << MOTOR_B_IN1) | (1ULL << MOTOR_B_IN2);
    io_conf.mode = GPIO_MODE_OUTPUT;
    io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&io_conf);

    // 初始停止
    gpio_set_level(MOTOR_A_IN1, 0);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 0);
    gpio_set_level(MOTOR_B_IN2, 0);

    ESP_LOGI(TAG, "[Motor] 初始化完成");
}

// ===========================
// 编码器初始化
// ===========================
static void encoder_init(void)
{
    // GPIO上拉
    gpio_config_t pull_conf = {};
    pull_conf.pin_bit_mask = (1ULL << ENCODER_L_A) | (1ULL << ENCODER_L_B) |
                             (1ULL << ENCODER_R_A) | (1ULL << ENCODER_R_B);
    pull_conf.mode = GPIO_MODE_INPUT;
    pull_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    pull_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    pull_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&pull_conf);

    // PCNT 单元配置
    pcnt_unit_config_t unit_conf = {};
    unit_conf.high_limit = 32767;
    unit_conf.low_limit = -32768;
    unit_conf.flags.accum_count = 1;  // 软件累加防溢出

    // 左轮 PCNT
    pcnt_new_unit(&unit_conf, &g_pcnt_l);

    // 左轮通道0: A相边沿 + B相电平
    pcnt_chan_config_t chan_conf = {};
    chan_conf.edge_gpio_num = ENCODER_L_A;
    chan_conf.level_gpio_num = ENCODER_L_B;
    pcnt_channel_handle_t pcnt_ch_l0 = NULL;
    pcnt_new_channel(g_pcnt_l, &chan_conf, &pcnt_ch_l0);
    pcnt_channel_set_edge_action(pcnt_ch_l0,
        PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_DECREASE);
    pcnt_channel_set_level_action(pcnt_ch_l0,
        PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE);

    // 左轮通道1: B相边沿 + A相电平 (4倍频)
    chan_conf.edge_gpio_num = ENCODER_L_B;
    chan_conf.level_gpio_num = ENCODER_L_A;
    pcnt_channel_handle_t pcnt_ch_l1 = NULL;
    pcnt_new_channel(g_pcnt_l, &chan_conf, &pcnt_ch_l1);
    pcnt_channel_set_edge_action(pcnt_ch_l1,
        PCNT_CHANNEL_EDGE_ACTION_DECREASE, PCNT_CHANNEL_EDGE_ACTION_INCREASE);
    pcnt_channel_set_level_action(pcnt_ch_l1,
        PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE);

    // 右轮 PCNT
    pcnt_new_unit(&unit_conf, &g_pcnt_r);

    // 右轮通道0
    chan_conf.edge_gpio_num = ENCODER_R_A;
    chan_conf.level_gpio_num = ENCODER_R_B;
    pcnt_channel_handle_t pcnt_ch_r0 = NULL;
    pcnt_new_channel(g_pcnt_r, &chan_conf, &pcnt_ch_r0);
    pcnt_channel_set_edge_action(pcnt_ch_r0,
        PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_DECREASE);
    pcnt_channel_set_level_action(pcnt_ch_r0,
        PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE);

    // 右轮通道1
    chan_conf.edge_gpio_num = ENCODER_R_B;
    chan_conf.level_gpio_num = ENCODER_R_A;
    pcnt_channel_handle_t pcnt_ch_r1 = NULL;
    pcnt_new_channel(g_pcnt_r, &chan_conf, &pcnt_ch_r1);
    pcnt_channel_set_edge_action(pcnt_ch_r1,
        PCNT_CHANNEL_EDGE_ACTION_DECREASE, PCNT_CHANNEL_EDGE_ACTION_INCREASE);
    pcnt_channel_set_level_action(pcnt_ch_r1,
        PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE);

    // 使能并启动
    pcnt_unit_enable(g_pcnt_l);
    pcnt_unit_enable(g_pcnt_r);
    pcnt_unit_clear_count(g_pcnt_l);
    pcnt_unit_clear_count(g_pcnt_r);
    pcnt_unit_start(g_pcnt_l);
    pcnt_unit_start(g_pcnt_r);

    // pcnt_new_channel 会覆盖GPIO配置，重新启用上拉
    gpio_pullup_en(ENCODER_L_A);
    gpio_pullup_en(ENCODER_L_B);
    gpio_pullup_en(ENCODER_R_A);
    gpio_pullup_en(ENCODER_R_B);

    ESP_LOGI(TAG, "[Encoder] 初始化完成");
}

// ===========================
// 读取编码器
// ===========================
static void encoder_read(int *l_count, int *r_count)
{
    int l_val, r_val;
    pcnt_unit_get_count(g_pcnt_l, &l_val);
    pcnt_unit_get_count(g_pcnt_r, &r_val);
    *l_count = l_val;
    *r_count = r_val;
}

// ===========================
// 启动电机AB (正转)
// ===========================
static void motor_forward(uint8_t speed)
{
    gpio_set_level(MOTOR_A_IN1, 1);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 1);
    gpio_set_level(MOTOR_B_IN2, 0);
    ledc_set_duty(LEDC_MODE, MOTOR_A_CHANNEL, speed);
    ledc_set_duty(LEDC_MODE, MOTOR_B_CHANNEL, speed);
    ledc_update_duty(LEDC_MODE, MOTOR_A_CHANNEL);
    ledc_update_duty(LEDC_MODE, MOTOR_B_CHANNEL);
    ESP_LOGI(TAG, "[MotorAB] 正转 占空比=%d", speed);
}

// ===========================
// 编码器打印任务
// ===========================
static void encoder_print_task(void *arg)
{
    while (1) {
        int l_count = 0, r_count = 0;
        encoder_read(&l_count, &r_count);
        ESP_LOGI(TAG, "[Encoder] 左轮=%d  右轮=%d", l_count, r_count);
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

// ===========================
// 主函数
// ===========================
extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "电机编码器测试 (20%%占空比)");
    ESP_LOGI(TAG, "========================================");

    motor_init();
    encoder_init();

    ESP_LOGI(TAG, "等待5秒...");
    vTaskDelay(pdMS_TO_TICKS(5000));

    // 20% 占空比 = 255 * 0.2 = 51
    uint8_t duty_20 = 51;
    ESP_LOGI(TAG, "启动电机AB (20%%占空比=%d)", duty_20);
    motor_forward(duty_20);

    xTaskCreate(encoder_print_task, "enc_print", 2048, NULL, 3, NULL);

    ESP_LOGI(TAG, "测试运行中...");
}
