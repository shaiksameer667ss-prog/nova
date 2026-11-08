class Vault:
    """A vault system."""
    def __init__(self):
        self.items = []
        self._token_valid = False
        self._pending = False

    def open(self):
        self._token_valid = True
        self._pending = False

    def add_item(self, item):
        self.items.append(item)
        self._pending = True
        self._token_valid = False

    def refresh(self):
        if not self._pending: return
        self._token_valid = True
        self._pending = False

    def commit(self):
        if not self._token_valid:
            raise PermissionError("Token invalid.")
        return self.items

def store_items(items):
    v = Vault()
    v.open()
    for i in items:
        v.add_item(i)
    return v.commit()