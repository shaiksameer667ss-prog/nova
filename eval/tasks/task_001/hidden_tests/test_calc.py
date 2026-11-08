from calc import sum_to


def test_sum_to_5():
    assert sum_to(5) == 15  # 1+2+3+4+5


def test_sum_to_1():
    assert sum_to(1) == 1


def test_sum_to_10():
    assert sum_to(10) == 55