"""
生成一个10x10的二维矩阵，每个位置记录该点有多少邻居
邻居定义：上下左右四个方向的相邻点（不包括对角线）
"""
def matrix1(rows=10, cols=10):
    """
    创建一个矩阵，每个位置的值表示该位置有多少个邻居

    Args:
        rows: 矩阵行数
        cols: 矩阵列数

    Returns:
        二维列表，每个元素表示该位置的邻居数量
    """
    # 初始化矩阵
    matrix = [[0 for _ in range(cols)] for _ in range(rows)]

    # 四个方向：上、下、左、右
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    # 遍历每个位置
    for i in range(rows):
        for j in range(cols):
            neighbor_count = 0

            # 检查四个方向的邻居
            for di, dj in directions:
                ni, nj = i + di, j + dj
                # 如果邻居在矩阵范围内，计数加1
                if 0 <= ni < rows and 0 <= nj < cols:
                    neighbor_count += 1

            matrix[i][j] = neighbor_count

    return matrix



def matrix2(rows=10, cols=10):
    """
    创建一个修改后的矩阵，将左上角(0,0)到(2,4)的区域置为0
    节点的值表示该节点有多少个非0的邻居节点

    Args:
        rows: 矩阵行数
        cols: 矩阵列数

    Returns:Q
        修改后的二维列表
    """
    # 初始化矩阵，先全部设为1（表示节点存在）
    exists = [[1 for _ in range(cols)] for _ in range(rows)]

    # 将左上角(0,0)到(2,4)的区域标记为不存在（0）
    for i in range(3):  # 行 0, 1, 2
        for j in range(5):  # 列 0, 1, 2, 3, 4
            exists[i][j] = 0

    # 创建结果矩阵
    matrix = [[0 for _ in range(cols)] for _ in range(rows)]

    # 四个方向：上、下、左、右
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    # 遍历每个位置，计算非0邻居数量
    for i in range(rows):
        for j in range(cols):
            if exists[i][j] == 0:
                # 如果当前节点是0，则值为0
                matrix[i][j] = 0
            else:
                # 计算有多少个非0的邻居
                neighbor_count = 0
                for di, dj in directions:
                    ni, nj = i + di, j + dj
                    # 如果邻居在矩阵范围内且不为0，计数加1
                    if 0 <= ni < rows and 0 <= nj < cols and exists[ni][nj] == 1:
                        neighbor_count += 1
                matrix[i][j] = neighbor_count

    return matrix


def print_matrix(matrix):
    """
    打印矩阵，格式化输出
    """
    print("10x10 邻居数量矩阵：")
    print("-" * 30)
    for row in matrix:
        print(" ".join(f"{val:2d}" for val in row))
    print("-" * 30)


def matrix3(rows=10, cols=10):
    """
    创建另一个修改后的矩阵，中间区域有障碍物
    将(4,4)到(6,6)的区域置为0（中心障碍物）

    Args:
        rows: 矩阵行数
        cols: 矩阵列数

    Returns:
        修改后的二维列表
    """
    # 初始化矩阵，先全部设为1（表示节点存在）
    exists = [[1 for _ in range(cols)] for _ in range(rows)]

    # 将中间(4,4)到(6,6)的区域标记为不存在（0）
    for i in range(4, 7):  # 行 4, 5, 6
        for j in range(4, 7):  # 列 4, 5, 6
            exists[i][j] = 0

    # 创建结果矩阵
    matrix = [[0 for _ in range(cols)] for _ in range(rows)]

    # 四个方向：上、下、左、右
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    # 遍历每个位置，计算非0邻居数量
    for i in range(rows):
        for j in range(cols):
            if exists[i][j] == 0:
                # 如果当前节点是0，则值为0
                matrix[i][j] = 0
            else:
                # 计算有多少个非0的邻居
                neighbor_count = 0
                for di, dj in directions:
                    ni, nj = i + di, j + dj
                    # 如果邻居在矩阵范围内且不为0，计数加1
                    if 0 <= ni < rows and 0 <= nj < cols and exists[ni][nj] == 1:
                        neighbor_count += 1
                matrix[i][j] = neighbor_count

    return matrix

def matrix4(rows=10, cols=10):
    """
    创建一个修改后的矩阵，将左上角(0,0)到(2,4)的区域置为0
    节点的值表示该节点有多少个非0的邻居节点

    Args:
        rows: 矩阵行数
        cols: 矩阵列数

    Returns:Q
        修改后的二维列表
    """
    # 初始化矩阵，先全部设为1（表示节点存在）
    exists = [[1 for _ in range(cols)] for _ in range(rows)]

    # 将左上角(0,0)到(2,4)的区域标记为不存在（0）
    for i in range(3):  # 行 0, 1, 2
        for j in range(5):  # 列 0, 1, 2, 3, 4
            exists[i][j] = 0

    # 将中间(4,4)到(6,6)的区域标记为不存在（0）
    for i in range(9, 10):  # 行 4, 5, 6
        for j in range(0, 4):  # 列 4, 5, 6
            exists[i][j] = 0
    # 将中间(4,4)到(6,6)的区域标记为不存在（0）
    for i in range(4, 7):  # 行 4, 5, 6
        for j in range(4, 7):  # 列 4, 5, 6
            exists[i][j] = 0
    # 创建结果矩阵
    matrix = [[0 for _ in range(cols)] for _ in range(rows)]

    # 四个方向：上、下、左、右
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    # 遍历每个位置，计算非0邻居数量
    for i in range(rows):
        for j in range(cols):
            if exists[i][j] == 0:
                # 如果当前节点是0，则值为0
                matrix[i][j] = 0
            else:
                # 计算有多少个非0的邻居
                neighbor_count = 0
                for di, dj in directions:
                    ni, nj = i + di, j + dj
                    # 如果邻居在矩阵范围内且不为0，计数加1
                    if 0 <= ni < rows and 0 <= nj < cols and exists[ni][nj] == 1:
                        neighbor_count += 1
                matrix[i][j] = neighbor_count

    return matrix
if __name__ == "__main__":
    # 创建10x10矩阵
    neighbor_matrix = matrix1(10, 10)
    print_matrix(neighbor_matrix)

    # 创建修改后的矩阵
    print("\n修改后的矩阵（左上角(0,0)到(2,4)置为0）：")
    modified_matrix = matrix2(10, 10)
    print_matrix(modified_matrix)

    # 创建第三个矩阵
    print("\n第三个矩阵（中间(4,4)到(6,6)置为0）：")
    matrix3_data = matrix3(10, 10)
    print_matrix(matrix3_data)



    # 创建第三个矩阵
    print("\n第三个矩阵（中间(4,4)到(6,6)置为0）：")
    matrix4_data = matrix4()
    print_matrix(matrix4_data)


