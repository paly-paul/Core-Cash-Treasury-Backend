def detect_format(filename: str, content_bytes: bytes) -> str:
    """
    Detect file format from filename and content.

    Detection order (first match wins):
    1. If filename ends with .xml (case-insensitive) → CAMT053
    2. If content starts with b"01," → BAI2
    3. If content starts with b":20:" → MT940
    4. If filename ends with .csv (case-insensitive) → CSV
    5. → UNKNOWN

    Returns: "BAI2" | "CAMT053" | "MT940" | "CSV" | "UNKNOWN"
    """
    # Check by extension first (XML only)
    if filename.lower().endswith(".xml"):
        return "CAMT053"

    # Check first 64 bytes for content patterns
    first_bytes = content_bytes[:64]

    # BAI2: starts with "01,"
    if first_bytes.startswith(b"01,"):
        return "BAI2"

    # MT940: starts with ":20:"
    if first_bytes.startswith(b":20:"):
        return "MT940"

    # CSV extension
    if filename.lower().endswith(".csv"):
        return "CSV"

    return "UNKNOWN"
