class ParcelPipe:
    """
    A system for staging and committing parcel records.
    Protocol-X requires that any mutation (add_record) invalidates the auth token.
    The token must be refreshed AFTER the last mutation, and BEFORE finalize().
    """
    def __init__(self):
        self.records = []
        self._auth_valid = False
        self._mutated_since_refresh = False

    def authenticate(self):
        self._auth_valid = True
        self._mutated_since_refresh = False

    def add_record(self, record_id):
        self.records.append(record_id)
        self._mutated_since_refresh = True
        self._auth_valid = False # Mutation invalidates auth

    def refresh_auth(self):
        if not self._mutated_since_refresh:
            return
        self._auth_valid = True
        self._mutated_since_refresh = False

    def finalize(self):
        if not self._auth_valid:
            raise PermissionError("Auth token invalid. Mutations require refresh before finalize.")
        return self.records

# BUG: This function doesn't follow Protocol-X
def process_batch(records_to_add):
    pipe = ParcelPipe()
    pipe.authenticate()
    for r in records_to_add:
        pipe.add_record(r)
    # BUG: missing pipe.refresh_auth() here
    return pipe.finalize()