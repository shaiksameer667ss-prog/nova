def split_fields(source: str) -> list[str]:
    """Split at semicolons outside quoted values, respecting escapes."""
    fields = []
    start = 0
    in_quotes = False
    escaped = False

    for index, char in enumerate(source):
        if in_quotes and escaped:
            escaped = False
            continue

        if in_quotes and char == "\\":
            escaped = True
            continue

        if char == '"':
            in_quotes = not in_quotes
        elif char == ";" and not in_quotes:
            fields.append(source[start:index].strip())
            start = index + 1

    if in_quotes:
        raise ValueError("Unterminated quoted value")

    fields.append(source[start:].strip())
    return fields