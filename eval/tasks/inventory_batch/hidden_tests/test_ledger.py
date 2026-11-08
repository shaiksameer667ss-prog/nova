from ledger import InventoryLedger

def test_basic_commit():
    ledger = InventoryLedger()
    ledger.stage_adjustment("apple", 5)
    ledger.stage_adjustment("banana", 3)
    ledger.commit_batch()
    assert ledger.get_stock("apple") == 5
    assert ledger.get_stock("banana") == 3

def test_double_commit_does_not_double_count():
    ledger = InventoryLedger()
    ledger.stage_adjustment("apple", 5)
    ledger.commit_batch()
    ledger.commit_batch() # Should not add another 5
    assert ledger.get_stock("apple") == 5

def test_stage_after_commit():
    ledger = InventoryLedger()
    ledger.stage_adjustment("apple", 5)
    ledger.commit_batch()
    ledger.stage_adjustment("apple", 2)
    ledger.commit_batch()
    assert ledger.get_stock("apple") == 7