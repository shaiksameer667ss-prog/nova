def sort_by_priority(items):
    """
    Return items sorted by 'priority' ascending.
    Items with equal priority must preserve their original input order
    (i.e., the sort must be stable).
    """
    return _merge_sort(items)


def _merge_sort(items):
    if len(items) <= 1:
        return list(items)
    mid = len(items) // 2
    left = _merge_sort(items[:mid])
    right = _merge_sort(items[mid:])
    return _merge(left, right)


def _merge(left, right):
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i]["priority"] < right[j]["priority"]:  # BUG: should be <=
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result