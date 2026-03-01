#include <stdio.h>
#include <math.h>
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ESP-DL头文件
#include "dl_model_base.hpp"
#include "dl_tensor_base.hpp"
#include "fbs_model.hpp"
#include "fbs_loader.hpp"

// 模型数据（由pack_model.py生成）
#include "model_data.h"

static const char *TAG = "SIN_MODEL";

// 模型句柄
static dl::Model *model = NULL;

/**
 * @brief 初始化模型
 */
static esp_err_t model_init(void) {
    ESP_LOGI(TAG, "初始化ESP-DL模型...");

    // try to allocate with nothrow to avoid exceptions
    fbs::FbsModel *fbs_model = new (std::nothrow) fbs::FbsModel(
        (const void *)model_data,
        model_data_size,
        fbs::MODEL_LOCATION_IN_FLASH_RODATA,
        false,
        false,
        false,
        true
    );
    if (!fbs_model) {
        ESP_LOGE(TAG, "创建 FbsModel 失败");
        return ESP_FAIL;
    }

    model = new (std::nothrow) dl::Model(fbs_model, 0, dl::MEMORY_MANAGER_GREEDY);
    if (!model) {
        ESP_LOGE(TAG, "创建 dl::Model 失败");
        delete fbs_model;
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "模型加载成功，大小: %d 字节", model_data_size);
    return ESP_OK;
}

/**
 * @brief 执行推理
 */
static esp_err_t model_inference(float input_val, float *output_val) {
    if (model == NULL) {
        ESP_LOGE(TAG, "模型未初始化");
        return ESP_FAIL;
    }

    // 准备输入数据
    float input_data[1] = {input_val};

    // 创建输入tensor（1x1 float32）
    std::vector<int> shape = {1, 1};
    dl::TensorBase tensor_input(shape, input_data, 0, dl::DATA_TYPE_FLOAT, true);

    // 运行推理
    model->run(&tensor_input);

    // 获取输出（使用引用）
    std::map<std::string, dl::TensorBase *> &outputs = model->get_outputs();
    if (outputs.empty()) {
        ESP_LOGE(TAG, "获取输出失败");
        return ESP_FAIL;
    }

    // 获取第一个输出tensor
    dl::TensorBase *tensor_output = outputs.begin()->second;
    float *output_ptr = tensor_output->get_element_ptr<float>();
    *output_val = output_ptr[0];

    return ESP_OK;
}

extern "C" void app_main(void) {
    ESP_LOGI(TAG, "========== SIN模型推理示例 ==========");

    // 初始化模型
    if (model_init() != ESP_OK) {
        ESP_LOGE(TAG, "模型初始化失败，程序终止");
        return;
    }

    // 测试数据：10个x值（0到2π均匀分布）
    const int num_tests = 10;
    float test_inputs[num_tests];
    for (int i = 0; i < num_tests; i++) {
        test_inputs[i] = (float)i * (2.0f * M_PI / (float)(num_tests - 1));
    }

    int iteration = 0;
    while (1) {
        iteration++;
        ESP_LOGI(TAG, "\n========== 迭代 %d ==========", iteration);

        float total_error = 0.0f;

        for (int i = 0; i < num_tests; i++) {
            float x = test_inputs[i];
            float y_pred, y_true;

            // 获取开始时间
            int64_t start_time = esp_timer_get_time();

            // 执行推理
            esp_err_t ret = model_inference(x, &y_pred);

            // 获取结束时间
            int64_t end_time = esp_timer_get_time();
            float inference_time_ms = (float)(end_time - start_time) / 1000.0f;

            if (ret == ESP_OK) {
                // 计算真实值
                y_true = sinf(x);

                // 计算误差
                float error = fabsf(y_pred - y_true);
                total_error += error;

                // 输出结果
                ESP_LOGI(TAG, "[%2d] x=%6.3f rad (%6.1f°) | 预测=%7.4f | 真实=%7.4f | 误差=%7.4f | 耗时=%.2f ms",
                         i, x, x * 180.0f / M_PI, y_pred, y_true, error, inference_time_ms);
            } else {
                ESP_LOGE(TAG, "[%2d] x=%6.3f rad | 推理失败", i, x);
            }

            // 小延迟，避免串口输出过快
            vTaskDelay(pdMS_TO_TICKS(10));
        }

        // 输出平均误差
        float avg_error = total_error / num_tests;
        ESP_LOGI(TAG, "平均绝对误差: %.6f\n", avg_error);

        // 等待3秒后进行下一轮测试
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}