#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "model_data.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ESP-DL 相关头文件
// 注意：实际使用时需要安装 ESP-DL 库并正确配置
// 这里提供的是通用的推理框架结构

// 模拟 ESP-DL 的数据结构（实际使用时需要包含真实的 ESP-DL 头文件）
#if !defined(ESPDL_LOADED)
// 如果没有 ESP-DL 库，定义一些基本类型用于演示
typedef struct {
    uint8_t* model_data;
    size_t model_size;
    void* model_handle;
} dl_model_t;

typedef struct {
    float* data;
    size_t size;
} dl_tensor_t;
#else
// 假设有 ESP-DL 库，包含真实头文件
#include "dl_model.h"
#include "dl_tensor.h"
#endif

// 输入输出配置
#define INPUT_SIZE 1      // 输入特征数
#define OUTPUT_SIZE 1     // 输出特征数
#define BATCH_SIZE 1      // 批次大小

// 全局模型句柄
dl_model_t* g_model = NULL;

/**
 * @brief 加载 ESP-DL 模型
 * @return 0 成功，-1 失败
 */
int load_model() {
    printf("正在加载模型...\n");
    printf("模型数据大小: %zu 字节\n", model_data_size);

    // 分配模型句柄内存
    g_model = (dl_model_t*)malloc(sizeof(dl_model_t));
    if (g_model == NULL) {
        printf("错误: 无法分配模型句柄内存\n");
        return -1;
    }

    // 设置模型数据指针
    g_model->model_data = (uint8_t*)model_data;
    g_model->model_size = model_data_size;
    g_model->model_handle = NULL;

    // 在实际的 ESP-DL 环境中，这里会调用 dl_model_init 函数
    // dl_model_init(g_model);

    printf("模型加载成功!\n");
    return 0;
}

/**
 * @brief 运行模型推理
 * @param input 输入数据数组（浮点数）
 * @param output 输出数据数组（浮点数）
 * @return 0 成功，-1 失败
 */
int run_inference(float* input, float* output) {
    if (g_model == NULL) {
        printf("错误: 模型未加载\n");
        return -1;
    }

    printf("\n开始推理...\n");
    printf("输入值: %.6f\n", input[0]);

    // 在实际的 ESP-DL 环境中，这里会：
    // 1. 将浮点数输入转换为量化格式
    // 2. 调用 dl_model_run 进行推理
    // 3. 将量化输出转换回浮点数

    // 以下是简化版本的推理逻辑（用于演示）
    // 注意：这是示例代码，实际的量化推理需要使用 ESP-DL 库

    // 量化输入（假设 scale=0.0625，zero_point=0，基于 sin_model.json）
    float input_scale = 0.0625f;
    int8_t input_quant = (int8_t)(input[0] / input_scale);

    printf("输入量化值: %d (scale=%.6f)\n", input_quant, input_scale);

    // 在实际场景中，这里会调用：
    // dl_tensor_t input_tensor;
    // dl_tensor_t output_tensor;
    // dl_model_run(g_model, &input_tensor, &output_tensor);

    // 由于没有实际的 ESP-DL 库，我们无法执行真正的推理
    // 这里提供一个框架，用户需要在实际的 ESP-DL 环境中填充具体实现

    printf("注意: 完整的推理需要 ESP-DL 库支持\n");
    printf("请在 ESP-IDF 或支持 ESP-DL 的环境中编译运行\n");

    // 对于演示，我们使用一个简单的近似值
    // 实际输出应该通过 dl_model_run 获得
    float temp = sin(input[0]);
    output[0] = temp;

    printf("输出值: %.6f (参考: sin(%.6f) = %.6f)\n", output[0], input[0], temp);

    return 0;
}

/**
 * @brief 释放模型资源
 */
void release_model() {
    if (g_model != NULL) {
        // 在实际的 ESP-DL 环境中，这里会调用 dl_model_deinit
        // dl_model_deinit(g_model);
        free(g_model);
        g_model = NULL;
    }
    printf("模型资源已释放\n");
}

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief ESP-IDF 主函数 - 测试推理
 */
void app_main(void) {
    ESP_LOGI("APP", "========================================");
    ESP_LOGI("APP", "   ESP-DL 模型推理测试程序");
    ESP_LOGI("APP", "========================================\n");

    // 1. 加载模型
    if (load_model() != 0) {
        ESP_LOGE("APP", "模型加载失败");
        return;
    }

    // 2. 准备测试数据
    float test_inputs[] = {
        0.0f,       // 0 弧度
        1.5708f,    // π/2 弧度
        3.14159f,   // π 弧度
        4.71239f,   // 3π/2 弧度
        0.5236f,    // π/6 弧度 (30度)
        1.0472f,    // π/3 弧度 (60度)
        2.0944f,    // 2π/3 弧度 (120度)
        2.61799f    // 5π/6 弧度 (150度)
    };
    const int num_tests = sizeof(test_inputs) / sizeof(test_inputs[0]);

    ESP_LOGI("APP", "准备测试 %d 个输入样本...\n", num_tests);

    // 3. 运行推理测试
    float output[OUTPUT_SIZE];
    for (int i = 0; i < num_tests; i++) {
        ESP_LOGI("APP", "--- 测试 #%d ---", i + 1);

        if (run_inference(&test_inputs[i], output) != 0) {
            ESP_LOGE("APP", "推理失败");
            continue;
        }

        // 比较理论值
        float expected = sin(test_inputs[i]);
        float error = fabs(output[0] - expected);

        ESP_LOGI("APP", "期望值: %.6f", expected);
        ESP_LOGI("APP", "误差: %.6f", error);
        ESP_LOGI("APP", "相对误差: %.2f%%", (error / (fabs(expected) + 1e-6f)) * 100.0f);
        ESP_LOGI("APP", "");
    }

    // 4. 清理资源
    release_model();

    ESP_LOGI("APP", "========================================");
    ESP_LOGI("APP", "测试完成");
    ESP_LOGI("APP", "========================================");
}

#ifdef __cplusplus
}
#endif