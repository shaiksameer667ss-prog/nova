import ast

from tokenizer import split_fields


def parse_record(source: str) -> dict[str, str]:
    if not isinstance(source, str):
        raise TypeError("source must be a string")

    if not source.strip():
        return {}

    result = {}

    for field in split_fields(source):
        if not field:
            continue

        key, separator, raw_value = field.partition("=")
        key = key.strip()

        if not separator or not key:
            raise ValueError(f"Invalid field: {field!r}")

        raw_value = raw_value.strip()

        if raw_value.startswith('"'):
            try:
                value = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(
                    f"Invalid quoted value for {key!r}"
                ) from exc

            if not isinstance(value, str):
                raise ValueError(f"Expected a string value for {key!r}")
        else:
            value = raw_value

        result[key] = value

    return result