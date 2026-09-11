def calculate_total(prices, discount=1.0):
    """计算折扣后的总价；discount 为折扣系数，例如 0.8 表示八折。"""
    if not 0 <= discount <= 1:
        raise ValueError("discount 必须在 0 到 1 之间")
    return round(sum(prices) * discount, 2)


print(calculate_total([100, 50, 25], discount=0.8))
