from sort_items import sort_by_priority


def test_sorted_by_priority():
    items = [
        {"id": "a", "priority": 2},
        {"id": "b", "priority": 1},
        {"id": "c", "priority": 3},
    ]
    result = sort_by_priority(items)
    assert [x["id"] for x in result] == ["b", "a", "c"]


def test_stability_on_ties():
    items = [
        {"id": "a", "priority": 2},
        {"id": "b", "priority": 2},
        {"id": "c", "priority": 1},
        {"id": "d", "priority": 2},
    ]
    result = sort_by_priority(items)
    assert [x["id"] for x in result] == ["c", "a", "b", "d"]


def test_empty():
    assert sort_by_priority([]) == []


def test_all_equal():
    items = [{"id": str(i), "priority": 1} for i in range(5)]
    result = sort_by_priority(items)
    assert [x["id"] for x in result] == ["0", "1", "2", "3", "4"]