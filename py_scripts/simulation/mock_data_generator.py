def print_matrix(matrix):
    """
    打印矩阵，格式化输出
    """
    print("10x10 邻居数量矩阵：")
    print("-" * 30)
    for row in matrix:
        print(" ".join(f"{val:2d}" for val in row))
    print("-" * 30)


def matrix1(rows=10, cols=10):
    """
    创建一个模拟环境矩阵，包含多个障碍物区域
    
    注意：所有非障碍物节点初始时都设为4（假设有4个邻居），
    因为节点在搜索前不知道周围实际有几个邻居

    Args:
        rows: 矩阵行数
        cols: 矩阵列数

    Returns:
        修改后的二维列表
    """
    # 初始化矩阵，先全部设为1（表示节点存在）
    exists = [[1 for _ in range(cols)] for _ in range(rows)]

    # 将左上角(0,0)到(2,4)的区域标记为不存在（0）
    for i in range(3):  # 行 0, 1, 2
        for j in range(5):  # 列 0, 1, 2, 3, 4
            exists[i][j] = 0

    # 将中间(4,4)到(6,6)的区域标记为不存在（0）
    for i in range(9, 10):  # 行 9
        for j in range(0, 4):  # 列 0, 1, 2, 3
            exists[i][j] = 0
    # 将中间(4,4)到(6,6)的区域标记为不存在（0）
    for i in range(4, 7):  # 行 4, 5, 6
        for j in range(4, 7):  # 列 4, 5, 6
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


if __name__ == "__main__":
    matrix_data = matrix1()
    print_matrix(matrix_data)
