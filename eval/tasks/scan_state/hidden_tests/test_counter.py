from counter import Counter


def test_basic_flush():
    c = Counter()
    c.increment(2)
    c.increment(3)
    assert c.flush() == 5


def test_double_flush_does_not_double_count():
    c = Counter()
    c.increment(2)
    c.increment(3)
    assert c.flush() == 5
    assert c.flush() == 5


def test_increment_after_flush_accumulates():
    c = Counter()
    c.increment(2)
    assert c.flush() == 2
    c.increment(3)
    assert c.flush() == 5


def test_value_or_default_when_nothing_committed():
    c = Counter()
    assert c.value_or(99) == 99


def test_value_or_before_first_flush():
    c = Counter()
    c.increment(5)
    assert c.value_or(99) == 99


def test_value_or_after_flush():
    c = Counter()
    c.increment(7)
    c.flush()
    assert c.value_or(99) == 7


def test_flush_with_no_pending_returns_current_total():
    c = Counter()
    c.increment(4)
    c.flush()
    assert c.flush() == 4