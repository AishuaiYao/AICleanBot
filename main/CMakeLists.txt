set(srcs app_main.cpp)

set(requires
    esp_driver_gpio
    nvs_flash
    bt
)

idf_component_register(SRCS ${srcs}
                       REQUIRES ${requires})
