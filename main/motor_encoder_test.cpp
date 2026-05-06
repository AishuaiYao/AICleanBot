/**
 * @file motor_encoder_test.cpp
 * @brief 电机和编码器独立测试程序 - GPIO中断方式
 */

#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "driver/gptimer.h"
#include "esp_timer.h"

static const char *TAG = "MOTOR_TEST";

// ===========================
// 测试用引脚（用于自测）
// ===========================
#define TEST_OUT_PIN  GPIO_NUM_0    // 测试信号输出引脚
#define TEST_IN_PIN   GPIO_NUM_48   // 测试信号输入引脚（观察用）

// ===========================
// 编码器引脚定义
// ===========================
#define ENCODER_L_A   GPIO_NUM_38   // 左轮编码器A相
#define ENCODER_L_B   GPIO_NUM_47   // 左轮编码器B相
#define ENCODER_R_A   GPIO_NUM_21   // 右轮编码器A相
#define ENCODER_R_B   GPIO_NUM_14   // 右轮编码器B相

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
#define MOTOR_LEDC_MODE    LEDC_LOW_SPEED_MODE
#define MOTOR_LEDC_RESOLUTION  LEDC_TIMER_8_BIT
#define MOTOR_LEDC_FREQ     1000

#define MOTOR_A_CHANNEL  LEDC_CHANNEL_1
#define MOTOR_B_CHANNEL  LEDC_CHANNEL_2

// ===========================
// 全局计数器（volatile防止优化）
// ===========================
static volatile int g_int_count_l = 0;
static volatile int g_int_count_r = 0;
static int g_start_time_ms = 0;

// ===========================
// GPIO中断处理函数
// ===========================
static void IRAM_ATTR gpio_isr_handler(void* arg)
{
    int gpio_num = (int)(intptr_t)arg;
    if (gpio_num == ENCODER_L_A) {
        g_int_count_l++;
    } else if (gpio_num == ENCODER_R_A) {
        g_int_count_r++;
    }
}

// ===========================
// GPIO中断初始化
// ===========================
static void gpio_interrupt_init(void)
{
    ESP_LOGI(TAG, "[GPIO INT] 配置GPIO中断...");

    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << ENCODER_L_A) | (1ULL << ENCODER_R_A);
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_ANYEDGE;  // 上升沿和下降沿都触发
    gpio_config(&io_conf);

    gpio_install_isr_service(0);
    gpio_isr_handler_add(ENCODER_L_A, gpio_isr_handler, (void*)(intptr_t)ENCODER_L_A);
    gpio_isr_handler_add(ENCODER_R_A, gpio_isr_handler, (void*)(intptr_t)ENCODER_R_A);

    ESP_LOGI(TAG, "[GPIO INT] 中断配置完成，GPIO38/21已配置");
}

// ===========================
// GPIO中断自测（验证中断系统是否正常）
// ===========================
static volatile int g_test_count = 0;

static void IRAM_ATTR test_isr_handler(void* arg)
{
    g_test_count++;
}

static void test_gpio_interrupt_self(void)
{
    ESP_LOGI(TAG, "[SELFTEST] ========== GPIO中断自测 ==========");
    
    // 配置测试输出引脚（推挽输出）
    gpio_config_t out_conf = {};
    out_conf.pin_bit_mask = (1ULL << TEST_OUT_PIN);
    out_conf.mode = GPIO_MODE_OUTPUT;
    out_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    out_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    out_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&out_conf);
    
    // 配置测试输入引脚（中断输入）
    gpio_config_t in_conf = {};
    in_conf.pin_bit_mask = (1ULL << TEST_OUT_PIN);  // 输出接输入，形成自环
    in_conf.mode = GPIO_MODE_INPUT;
    in_conf.pull_up_en = GPIO_PULLUP_DISABLE;  // 不用内部上拉，因为是推挽驱动
    in_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    in_conf.intr_type = GPIO_INTR_ANYEDGE;
    gpio_config(&in_conf);
    
    // 安装中断服务
    gpio_install_isr_service(ESP_INTR_FLAG_SHARED);
    gpio_isr_handler_add(TEST_OUT_PIN, test_isr_handler, NULL);
    
    g_test_count = 0;
    
    // 手动翻转GPIO产生10个脉冲
    ESP_LOGI(TAG, "[SELFTEST] 产生10个测试脉冲到GPIO0...");
    for (int i = 0; i < 10; i++) {
        gpio_set_level(TEST_OUT_PIN, 0);
        gpio_set_level(TEST_OUT_PIN, 1);
    }
    
    vTaskDelay(pdMS_TO_TICKS(100));
    
    ESP_LOGI(TAG, "[SELFTEST] 预期中断次数: 20 (每脉冲2次边沿)");
    ESP_LOGI(TAG, "[SELFTEST] 实际中断次数: %d", g_test_count);
    
    if (g_test_count >= 15) {  // 允许一些误差
        ESP_LOGI(TAG, "[SELFTEST] ✓ GPIO中断系统工作正常！");
    } else {
        ESP_LOGI(TAG, "[SELFTEST] ✗ GPIO中断系统有问题！");
        ESP_LOGI(TAG, "[SELFTEST]   可能原因: ESP_INTR_FLAG配置或GPIO冲突");
    }
    
    ESP_LOGI(TAG, "[SELFTEST] ========== 自测完成 ==========");
    gpio_uninstall_isr_service();
}

// ===========================
// GPIO手动翻转测试（用于检测编码器信号）
// ===========================
static void test_gpio_toggle(void)
{
    ESP_LOGI(TAG, "[TEST] GPIO手动翻转测试 - 用于检测编码器是否正常");
    
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << ENCODER_L_A);
    io_conf.mode = GPIO_MODE_INPUT;  // 先切回输入
    io_conf.pull_up_en = GPIO_PULLUP_ENABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_ANYEDGE;
    gpio_config(&io_conf);
    
    int prev_level = gpio_get_level(ENCODER_L_A);
    ESP_LOGI(TAG, "[TEST] GPIO38初始电平: %d", prev_level);
    
    int sample_count = 0;
    int transitions = 0;
    
    // 采样 5 秒，观察电平变化
    for (int i = 0; i < 50; i++) {
        vTaskDelay(pdMS_TO_TICKS(100));
        int level = gpio_get_level(ENCODER_L_A);
        if (level != prev_level) {
            transitions++;
            ESP_LOGI(TAG, "[TEST] GPIO38电平变化: %d -> %d (第%d次)", 
                     prev_level, level, transitions);
            prev_level = level;
        }
        sample_count++;
    }
    
    if (transitions > 0) {
        ESP_LOGI(TAG, "[TEST] GPIO38在5秒内检测到%d次电平变化！编码器信号正常。", transitions);
    } else {
        ESP_LOGI(TAG, "[TEST] GPIO38在5秒内无电平变化！编码器信号异常！");
        ESP_LOGI(TAG, "[TEST] 请检查: 1)编码器是否连接 2)编码器是否供电 3)编码器输出类型");
    }
    
    ESP_LOGI(TAG, "[TEST] 即将启动电机测试...");
    vTaskDelay(pdMS_TO_TICKS(1000));
}

// ===========================
// 电机GPIO和PWM初始化
// ===========================
static void motor_init(void)
{
    ESP_LOGI(TAG, "[Motor] 初始化...");

    // LEDC定时器
    ledc_timer_config_t timer_conf = {};
    timer_conf.speed_mode = MOTOR_LEDC_MODE;
    timer_conf.duty_resolution = MOTOR_LEDC_RESOLUTION;
    timer_conf.timer_num = LEDC_TIMER_1;
    timer_conf.freq_hz = MOTOR_LEDC_FREQ;
    timer_conf.clk_cfg = LEDC_AUTO_CLK;
    ledc_timer_config(&timer_conf);

    // 电机A PWM
    ledc_channel_config_t motor_a_conf = {};
    motor_a_conf.gpio_num = MOTOR_A_PWM;
    motor_a_conf.speed_mode = MOTOR_LEDC_MODE;
    motor_a_conf.channel = MOTOR_A_CHANNEL;
    motor_a_conf.intr_type = LEDC_INTR_DISABLE;
    motor_a_conf.timer_sel = LEDC_TIMER_1;
    motor_a_conf.duty = 0;
    motor_a_conf.hpoint = 0;
    ledc_channel_config(&motor_a_conf);

    // 电机B PWM
    ledc_channel_config_t motor_b_conf = {};
    motor_b_conf.gpio_num = MOTOR_B_PWM;
    motor_b_conf.speed_mode = MOTOR_LEDC_MODE;
    motor_b_conf.channel = MOTOR_B_CHANNEL;
    motor_b_conf.intr_type = LEDC_INTR_DISABLE;
    motor_b_conf.timer_sel = LEDC_TIMER_1;
    motor_b_conf.duty = 0;
    motor_b_conf.hpoint = 0;
    ledc_channel_config(&motor_b_conf);

    // 方向控制GPIO
    gpio_config_t io_conf = {};
    io_conf.pin_bit_mask = (1ULL << MOTOR_A_IN1) | (1ULL << MOTOR_A_IN2) |
                           (1ULL << MOTOR_B_IN1) | (1ULL << MOTOR_B_IN2);
    io_conf.mode = GPIO_MODE_OUTPUT;
    io_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&io_conf);

    ESP_LOGI(TAG, "[Motor] 初始化完成");
}

// ===========================
// 启动电机
// ===========================
static void motor_start(uint8_t pwm)
{
    // 设置方向：正转 (IN1=1, IN2=0)
    gpio_set_level(MOTOR_A_IN1, 1);
    gpio_set_level(MOTOR_A_IN2, 0);
    gpio_set_level(MOTOR_B_IN1, 1);
    gpio_set_level(MOTOR_B_IN2, 0);

    // 设置PWM
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_A_CHANNEL, pwm);
    ledc_set_duty(MOTOR_LEDC_MODE, MOTOR_B_CHANNEL, pwm);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_A_CHANNEL);
    ledc_update_duty(MOTOR_LEDC_MODE, MOTOR_B_CHANNEL);
}

// ===========================
// 停止电机
// ===========================
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
}

// ===========================
// 主测试任务
// ===========================
static void motor_test_task(void *pvParameters)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "电机编码器测试 (GPIO中断方式)");
    ESP_LOGI(TAG, "========================================");

    // 初始化
    motor_init();
    
    // GPIO中断自测（确保中断系统工作）
    test_gpio_interrupt_self();
    
    gpio_interrupt_init();

    // 打印GPIO初始电平
    ESP_LOGI(TAG, "[GPIO] 初始电平: L_A=%d L_B=%d R_A=%d R_B=%d",
             gpio_get_level(ENCODER_L_A), gpio_get_level(ENCODER_L_B),
             gpio_get_level(ENCODER_R_A), gpio_get_level(ENCODER_R_B));

    // 手动GPIO采样测试（5秒）- 检测编码器是否有信号
    ESP_LOGI(TAG, "[Test] 开始GPIO电平采样测试（5秒）...");
    test_gpio_toggle();

    // 等待5秒
    ESP_LOGI(TAG, "[Test] 等待5秒后启动电机...");
    vTaskDelay(pdMS_TO_TICKS(5000));

    // 启动电机 (20% PWM)
    const uint8_t pwm = 51;  // 20% * 255
    motor_start(pwm);
    g_start_time_ms = esp_timer_get_time() / 1000;
    ESP_LOGI(TAG, "[Test] 电机启动 PWM=%d (20%%)", pwm);

    int last_l = 0, last_r = 0;

    while (1) {
        int now_ms = esp_timer_get_time() / 1000;
        int elapsed = now_ms - g_start_time_ms;

        int cur_l = g_int_count_l;
        int cur_r = g_int_count_r;

        int delta_l = cur_l - last_l;
        int delta_r = cur_r - last_r;
        last_l = cur_l;
        last_r = cur_r;

        ESP_LOGI(TAG, "[%ds] L=%d(+%d) R=%d(+%d)", 
                 elapsed / 1000, cur_l, delta_l, cur_r, delta_r);

        // 10秒后停止并显示结果
        if (elapsed >= 10000) {
            motor_stop();
            ESP_LOGI(TAG, "========================================");
            ESP_LOGI(TAG, "[RESULT] 10秒测试结果:");
            ESP_LOGI(TAG, "[RESULT] 左轮中断: %d次", cur_l);
            ESP_LOGI(TAG, "[RESULT] 右轮中断: %d次", cur_r);
            ESP_LOGI(TAG, "[RESULT] 左轮频率: %.1f Hz", cur_l / 10.0);
            ESP_LOGI(TAG, "[RESULT] 右轮频率: %.1f Hz", cur_r / 10.0);
            ESP_LOGI(TAG, "========================================");
            
            if (cur_l == 0 && cur_r == 0) {
                ESP_LOGI(TAG, "[ERROR] 无中断！检查编码器信号连接");
            } else {
                ESP_LOGI(TAG, "[OK] 编码器信号正常！问题在PCNT配置");
            }

            // 无限循环
            while (1) {
                vTaskDelay(pdMS_TO_TICKS(1000));
            }
        }

        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

// ===========================
// 入口
// ===========================
extern "C" void app_main(void)
{
    xTaskCreate(motor_test_task, "motor_test", 8192, NULL, 5, NULL);
}
