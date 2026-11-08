
class AuthSystem:
    """
    Manages user provisioning.

    Protocol: Any mutation (add_user) invalidates the current token.
    You must refresh the token AFTER the last mutation, BEFORE committing.
    """

    def __init__(self):
        self.users = []
        self._token_valid = False
        self._pending_changes = False

    def login(self):
        self._token_valid = True
        self._pending_changes = False

    def add_user(self, username):
        self.users.append(username)
        self._pending_changes = True
        self._token_valid = False

    def refresh_token(self):
        if not self._pending_changes:
            return
        self._token_valid = True
        self._pending_changes = False

    def commit_users(self):
        if not self._token_valid:
            raise PermissionError("Token invalid. Please refresh.")
        return self.users


def provision_users(usernames):
    auth = AuthSystem()
    auth.login()

    for u in usernames:
        auth.add_user(u)

    # BUG: missing auth.refresh_token() here
    return auth.commit_users()
