class SignalRegistry:
    def __init__(self):
        self.signals = []
        self._session_active = False
        self._state_dirty = False

    def open_session(self):
        self._session_active = True
        self._state_dirty = False

    def push_signal(self, sig):
        self.signals.append(sig)
        self._state_dirty = True
        self._session_active = False # Mutations invalidate session

    def renew_session(self):
        if not self._state_dirty:
            return
        self._session_active = True
        self._state_dirty = False

    def commit(self):
        if not self._session_active:
            raise ConnectionError("Session expired. Renew before commit.")
        return self.signals

# BUG: Missing the rule
def broadcast(signals):
    reg = SignalRegistry()
    reg.open_session()
    for s in signals:
        reg.push_signal(s)
    # BUG: missing reg.renew_session() here
    return reg.commit()