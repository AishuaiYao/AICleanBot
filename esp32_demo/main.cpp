#include <iostream>
#include <vector>
#include <cmath>
#include <fstream>
#include <cstring>
#include <cstdint>
#include <chrono>
#include <iomanip>

// ESP-DL相关头文件
#include "esp_dl_api.h"

// 模型配置结构体
struct ModelConfig {
    int input_size;
    int output_size;
};

// 模型数据结构
struct ModelData {
    uint8_t* weights;
    uint8_t* biases;
    int weight_count;
    int bias_count;
};

class ESPDLModel {
private:
    esp_dl_handle_t model_handle;
    ModelConfig config;
    
public:
    ESPDLModel(const std::string& model_path) {
        // 初始化ESP-DL
        esp_dl_init();
        
        // 加载模型
        model_handle = esp_dl_load_model(model_path.c_str());
        if (model_handle == nullptr) {
            throw std::runtime_error("Failed to load model: " + model_path);
        }
        
        // 获取模型配置
        config.input_size = esp_dl_get_input_size(model_handle);
        config.output_size = esp_dl_get_output_size(model_handle);
        
        std::cout << "Model loaded successfully!" << std::endl;
        std::cout << "Input size: " << config.input_size << std::endl;
        std::cout << "Output size: " << config.output_size << std::endl;
    }
    
    ~ESPDLModel() {
        // 释放模型
        esp_dl_unload_model(model_handle);
        esp_dl_deinit();
    }
    
    float predict(float input) {
        // 创建输入缓冲区
        float input_buffer[1] = {input};
        
        // 创建输出缓冲区
        float output_buffer[1] = {0};
        
        // 执行推理
        esp_dl_run_inference(model_handle, input_buffer, output_buffer);
        
        return output_buffer[0];
    }
    
    void run_batch_prediction(const std::vector<float>& inputs) {
        std::cout << "\nBatch Prediction Results:" << std::endl;
        std::cout << "------------------------" << std::endl;
        std::cout << std::left << std::setw(10) << "Input" 
                 << std::setw(15) << "Prediction" 
                 << std::setw(15) << "Actual Sine" 
                 << std::setw(15) << "Error" << std::endl;
        std::cout << std::string(55, '-') << std::endl;
        
        for (float input : inputs) {
            float prediction = predict(input);
            float actual = sin(input);
            float error = fabs(prediction - actual);
            
            std::cout << std::left << std::setw(10) << input 
                     << std::setw(15) << prediction 
                     << std::setw(15) << actual 
                     << std::setw(15) << error << std::endl;
        }
    }
};

int main() {
    try {
        // 创建模型实例
        ESPDLModel model("esp32_demo/sin_model.espdl");
        
        // 生成10个输入值
        std::vector<float> inputs;
        for (int i = 0; i < 10; i++) {
            inputs.push_back(i * 0.5f);  // 生成0, 0.5, 1.0, ..., 4.5
        }
        
        // 执行批量预测
        model.run_batch_prediction(inputs);
        
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
}