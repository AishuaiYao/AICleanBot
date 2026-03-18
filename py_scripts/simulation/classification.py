"""
Edge Endpoint Detection - Boundary Scanning Method
Detect endpoints on 4 edges to classify LINE, CROSS, T-SHAPE
Simple and efficient for ESP32S3 C++ implementation
"""

import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


def detect_edge_endpoints(image_path, edge_width=5, min_pixels=3):
    """
    Detect endpoints on 4 edges of the image
    
    Args:
        image_path: Path to image file
        edge_width: Width of edge region to scan (pixels)
        min_pixels: Minimum white pixels to consider as valid endpoint
    
    Returns:
        endpoints: Dictionary with top, bottom, left, right endpoints
        classification: LINE, CROSS, or T_SHAPE
        binary_img: Binary image
    """
    # Read image
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")
    
    height, width = img.shape
    
    # Convert to binary
    binary_img = (img > 127).astype(np.uint8)
    
    endpoints = {
        'top': None,
        'bottom': None,
        'left': None,
        'right': None
    }
    
    # 1. Scan TOP edge (first edge_width rows)
    x_sum, count = 0, 0
    for y in range(min(edge_width, height)):
        for x in range(width):
            if binary_img[y, x] == 1:
                x_sum += x
                count += 1
    
    if count >= min_pixels:
        endpoints['top'] = (x_sum // count, 0)
    
    # 2. Scan BOTTOM edge (last edge_width rows)
    x_sum, count = 0, 0
    for y in range(max(0, height - edge_width), height):
        for x in range(width):
            if binary_img[y, x] == 1:
                x_sum += x
                count += 1
    
    if count >= min_pixels:
        endpoints['bottom'] = (x_sum // count, height - 1)
    
    # 3. Scan LEFT edge (first edge_width columns)
    y_sum, count = 0, 0
    for x in range(min(edge_width, width)):
        for y in range(height):
            if binary_img[y, x] == 1:
                y_sum += y
                count += 1
    
    if count >= min_pixels:
        endpoints['left'] = (0, y_sum // count)
    
    # 4. Scan RIGHT edge (last edge_width columns)
    y_sum, count = 0, 0
    for x in range(max(0, width - edge_width), width):
        for y in range(height):
            if binary_img[y, x] == 1:
                y_sum += y
                count += 1
    
    if count >= min_pixels:
        endpoints['right'] = (width - 1, y_sum // count)
    
    # 5. Classification based on endpoint count
    endpoint_count = sum(1 for ep in endpoints.values() if ep is not None)
    
    if endpoint_count == 2:
        if endpoints['top'] and endpoints['bottom']:
            classification = "LINE (Vertical/Diagonal)"
        elif endpoints['left'] and endpoints['right']:
            classification = "LINE (Horizontal)"
        else:
            classification = "LINE (Diagonal)"
    elif endpoint_count == 4:
        classification = "CROSS"
    elif endpoint_count == 3:
        classification = "T-SHAPE"
    else:
        classification = "UNKNOWN"
    
    return endpoints, classification, binary_img


def visualize_edge_detection(image_path, save_path=None):
    """
    Visualize edge endpoint detection results
    """
    endpoints, classification, binary_img = detect_edge_endpoints(image_path)
    
    height, width = binary_img.shape
    
    # Create figure
    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.3)
    
    # 1. Original binary image with edge regions highlighted
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.imshow(binary_img * 255, cmap='gray')
    
    # Draw edge scanning regions
    edge_width = 5
    ax1.axhline(y=edge_width, color='red', linestyle='--', linewidth=1, alpha=0.5, label='Scan Region')
    ax1.axhline(y=height-edge_width, color='red', linestyle='--', linewidth=1, alpha=0.5)
    ax1.axvline(x=edge_width, color='red', linestyle='--', linewidth=1, alpha=0.5)
    ax1.axvline(x=width-edge_width, color='red', linestyle='--', linewidth=1, alpha=0.5)
    
    ax1.set_title('Binary Image with Edge Scan Regions', fontsize=12, fontweight='bold')
    ax1.set_xlabel('X (Column)')
    ax1.set_ylabel('Y (Row)')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # 2. Detected endpoints and lines
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.imshow(binary_img * 255, cmap='gray')
    
    # Draw detected endpoints
    colors = {'top': 'red', 'bottom': 'blue', 'left': 'green', 'right': 'orange'}
    for edge_name, endpoint in endpoints.items():
        if endpoint:
            ax2.plot(endpoint[0], endpoint[1], 'o', color=colors[edge_name], 
                    markersize=15, label=f'{edge_name.upper()}: ({endpoint[0]}, {endpoint[1]})',
                    markeredgecolor='white', markeredgewidth=2)
    
    # Draw lines connecting endpoints
    if endpoints['top'] and endpoints['bottom']:
        ax2.plot([endpoints['top'][0], endpoints['bottom'][0]], 
                [endpoints['top'][1], endpoints['bottom'][1]], 
                'r-', linewidth=3, alpha=0.7, label='Vertical Line')
    
    if endpoints['left'] and endpoints['right']:
        ax2.plot([endpoints['left'][0], endpoints['right'][0]], 
                [endpoints['left'][1], endpoints['right'][1]], 
                'g-', linewidth=3, alpha=0.7, label='Horizontal Line')
    
    ax2.set_title('Detected Endpoints & Lines', fontsize=12, fontweight='bold')
    ax2.set_xlabel('X (Column)')
    ax2.set_ylabel('Y (Row)')
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)
    
    # 3. Classification result
    ax3 = fig.add_subplot(gs[1, :])
    ax3.axis('off')
    
    # Count endpoints
    endpoint_count = sum(1 for ep in endpoints.values() if ep is not None)
    
    # Build result text
    result_text = f"CLASSIFICATION: {classification}\n\n"
    result_text += f"Detected Endpoints: {endpoint_count}\n\n"
    
    for edge_name, endpoint in endpoints.items():
        if endpoint:
            result_text += f"  • {edge_name.upper():8s}: ({endpoint[0]:3d}, {endpoint[1]:3d})\n"
        else:
            result_text += f"  • {edge_name.upper():8s}: None\n"
    
    result_text += "\n" + "="*50 + "\n"
    result_text += "Classification Logic:\n"
    result_text += "  • 2 endpoints (top+bottom or left+right) -> LINE\n"
    result_text += "  • 4 endpoints (all edges)              -> CROSS\n"
    result_text += "  • 3 endpoints                          -> T-SHAPE\n"
    result_text += "="*50 + "\n\n"
    
    # Add line tracking info for LINE case
    if "LINE" in classification:
        if endpoints['top'] and endpoints['bottom']:
            center_x = (endpoints['top'][0] + endpoints['bottom'][0]) // 2
            image_center = width // 2
            offset = center_x - image_center
            
            result_text += f"Line Tracking Info:\n"
            result_text += f"  Line Center X: {center_x}\n"
            result_text += f"  Image Center X: {image_center}\n"
            result_text += f"  Offset: {offset:+d} pixels\n"
            
            if offset > 5:
                result_text += f"  -> Action: TURN RIGHT\n"
            elif offset < -5:
                result_text += f"  -> Action: TURN LEFT\n"
            else:
                result_text += f"  -> Action: GO STRAIGHT\n"
    
    # Set color based on classification
    if "CROSS" in classification:
        color = 'red'
    elif "T-SHAPE" in classification:
        color = 'orange'
    elif "LINE" in classification:
        color = 'green'
    else:
        color = 'gray'
    
    ax3.text(0.5, 0.5, result_text, 
             ha='center', va='center', 
             fontsize=11, family='monospace',
             bbox=dict(boxstyle='round', facecolor=color, alpha=0.15))
    
    # Add main title
    fig.suptitle(f'Edge Endpoint Detection - {image_path.split("/")[-1]}', 
                 fontsize=16, fontweight='bold')
    
    # Save or show
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Edge detection result saved to: {save_path}")
    
    plt.show()
    
    return classification, endpoints


def analyze_all_images():
    """
    Analyze all three images using edge endpoint detection
    """
    images = [
        'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA_label\frame_000002_20260213_131845.png',
    ]
    
    print("=" * 70)
    print("Edge Endpoint Detection - Boundary Scanning Method")
    print("=" * 70)
    
    for img_path in images:
        print(f"\nAnalyzing image: {img_path}")
        save_path = img_path.replace('.png', '_edge_detection.png')
        classification, endpoints = visualize_edge_detection(img_path, save_path)
        
        print(f"Classification: {classification}")
        print(f"Endpoints detected:")
        for edge_name, endpoint in endpoints.items():
            if endpoint:
                print(f"  {edge_name:8s}: {endpoint}")
        print("-" * 70)


if __name__ == "__main__":
    analyze_all_images()