set(srcs app_main.cpp)

set(requires
    esp_driver_gpio
    esp_wifi
    esp_netif
    lwip
    nvs_flash
)

idf_component_register(SRCS ${srcs}
                       REQUIRES ${requires})
