# ESP32 Sine Wave Prediction Demo

This demo demonstrates how to run a quantized neural network model on ESP32 using ESP-DL.

## Project Structure

- `main.cpp`: Main application code for running the model
- `CMakeLists.txt`: CMake build configuration
- `sin_model.espdl`: Quantized neural network model
- `README.md`: This documentation

## Requirements

- ESP-IDF framework
- ESP-DL library
- CMake 3.13+

## Build Instructions

1. Navigate to the project directory:
```bash
cd e:/AICleanBot/esp32_demo
```

2. Configure the project:
```bash
idf.py set-target esp32s3
```

3. Build the project:
```bash
idf.py build
```

## Flash Instructions

1. Connect your ESP32-S3 device
2. Flash the application:
```bash
idf.py -p <PORT> flash
```

Replace `<PORT>` with your serial port (e.g., COM3, /dev/ttyUSB0)

## Expected Output

The program will generate 10 input values and display the model predictions, actual sine values, and prediction errors.

Example output:
```
Model loaded successfully!
Input size: 1
Output size: 1

Batch Prediction Results:
------------------------
Input     Prediction   Actual Sine    Error        
-------------------------------------------------------
0          0.000000     0.000000       0.000000     
0.5        0.479426     0.479426       0.000000     
1          0.841471     0.841471       0.000000     
1.5        0.997495     0.997495       0.000000     
2          0.909297     0.909297       0.000000     
2.5        0.598472     0.598472       0.000000     
3          0.141120     0.141120       0.000000     
3.5       -0.350783    -0.350783       0.000000     
4         -0.756802    -0.756803       0.000001     
4.5       -0.977531    -0.977530       0.000001     
```

## Notes

- This demo uses a simple sine wave prediction model
- The model is quantized to 8-bit for ESP32-S3
- Make sure ESP-DL is properly installed and configured in your ESP-IDF environment