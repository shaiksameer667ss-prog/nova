class Counter:
    """A counter that supports deferred commits via flush().

    Contract:
    - increment(n): queue an increment; does not commit.
    - flush(): commit all queued increments and return the total
      committed value. Repeated flush() calls with no new increments
      must return the same value (increments applied exactly once).
    - value_or(default): return the committed value, or `default` if
      nothing has been committed yet.
    """

    def __init__(self):
        self._committed = 0
        self._pending = []
        self._has_committed = False

    def increment(self, n=1):
        self._pending.append(n)

    def flush(self):
        if self._pending:
            self._committed += sum(self._pending)
            self._has_committed = True
            # INTENTIONAL BUG:
            # Missing self._pending.clear()
        return self._committed

    def value_or(self, default=0):
        if not self._has_committed:
            return default
        return self._committed