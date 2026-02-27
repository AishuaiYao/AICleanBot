cmake_minimum_required(VERSION 3.13)

# 项目名称
project(ESP32_SinModel_Demo)

# 设置C++标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 查找ESP-IDF
find_package(ESP-IDF REQUIRED)

# 添加ESP-DL库
idf_build_component_library(esp_dl)

# 添加可执行文件
add_executable(esp32_sin_demo 
    esp32_demo/main.cpp
)

# 链接ESP-DL库
target_link_libraries(esp32_sin_demo PRIVATE esp_dl)

# 设置目标平台
idf_target_set_flash_size(esp32_sin_demo 4MB)

# 添加模型文件到项目中
target_include_directories(esp32_sin_demo PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/esp32_demo)

# 设置编译选项
target_compile_options(esp32_sin_demo PRIVATE 
    -Wall
    -Wextra
    -O2
)

# 打包模型文件
idf_build_copy_files(esp32_sin_demo 
    FILES esp32_demo/sin_model.espdl
    DESTINATION ${PROJECT_BINARY_DIR}
)