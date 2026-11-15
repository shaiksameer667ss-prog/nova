def split_fields(source: str) -> list[str]:
    """Split a record at semicolons outside double-quoted values."""
    fields = []
    start = 0
    in_quotes = False

    for index, char in enumerate(source):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ";" and not in_quotes:
            fields.append(source[start:index].strip())
            start = index + 1

    if in_quotes:
        raise ValueError("Unterminated quoted value")

    fields.append(source[start:].strip())
    return fields
