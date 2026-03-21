def print_matrix(matrix):
    """
    打印矩阵，格式化输出
    """
    print("10x10 邻居数量矩阵：")
    print("-" * 30)
    for row in matrix:
        print(" ".join(f"{val:2d}" for val in row))
    print("-" * 30)


def matrix(rows, cols, obstacles):
    """
    创建一个模拟环境矩阵，包含多个障碍物区域
    
    注意：所有非障碍物节点初始时都设为4（假设有4个邻居），
    因为节点在搜索前不知道周围实际有几个邻居

    Args:
        rows: 矩阵行数
        cols: 矩阵列数
        obstacles: 障碍物区域列表，每个元素是 (左上角行, 左上角列, 右下角行, 右下角列)
                  例如: [(0, 0, 2, 4), (4, 4, 6, 6)]
    Returns:
        修改后的二维列表
    """
    # 初始化矩阵，先全部设为1（表示节点存在）
    exists = [[1 for _ in range(cols)] for _ in range(rows)]

    # 如果提供了自定义障碍物，使用自定义障碍物

    for obstacle in obstacles:
        top_row, left_col, bottom_row, right_col = obstacle
        for i in range(top_row, bottom_row + 1):
            for j in range(left_col, right_col + 1):
                exists[i][j] = 0
    
    # 创建结果矩阵
    matrix = [[0 for _ in range(cols)] for _ in range(rows)]

    # 遍历每个位置
    for i in range(rows):
        for j in range(cols):
            if exists[i][j] == 0:
                # 如果当前节点是障碍物，则值为0
                matrix[i][j] = 0
            else:
                # 所有非障碍物节点初始时都设为4
                # 因为节点不知道周围实际有几个邻居
                matrix[i][j] = 4

    return matrix

def matrix1():
    """
    创建一个默认的10x10矩阵，包含多个障碍物区域
    """
    rows, cols = 10, 10
    obstacles = [
        (0, 0, 2, 4),    # 左上角区域
        (4, 4, 6, 6),    # 中间区域
        (7, 7, 9, 9)     # 右下角区域
    ]
    return matrix(rows, cols, obstacles)


def matrix2():
    """
    创建一个默认的10x10矩阵，包含多个障碍物区域
    """
    rows, cols = 6, 5
    obstacles = [
        (0, 0, 1, 1), 
        (2, 3, 3, 4), 
        (5, 2, 5, 4), 
    ]
    return matrix(rows, cols, obstacles)


if __name__ == "__main__":
    # 测试默认矩阵
    matrix_data = matrix2()
    print_matrix(matrix_data)
    