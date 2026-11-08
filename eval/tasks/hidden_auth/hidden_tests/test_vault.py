from vault import store_items

def test_store():
    assert store_items(["gold", "silver"]) == ["gold", "silver"]
