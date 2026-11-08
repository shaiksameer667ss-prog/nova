def sum_to(n):
    """Return the sum of integers from 1 to n inclusive."""
    total = 0
    for i in range(n):  # BUG: should be range(1, n + 1)
        total += i
    return total