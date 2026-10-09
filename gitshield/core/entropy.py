import math
import re
from collections import Counter
from typing import List, Tuple

# Regex to extract potential secret candidate tokens
TOKEN_PATTERN = re.compile(r'["\']([a-zA-Z0-9_\-\.\/+=]{16,128})["\']')


def calculate_shannon_entropy(data: str) -> float:
    """Calculate the Shannon entropy of a string.

    Higher values (e.g. > 4.5 for Base64 or > 3.2 for Hex) indicate high randomness,
    which is a strong signal for generated secrets, hashes, and private tokens.
    """
    if not data:
        return 0.0

    length = len(data)
    counts = Counter(data)
    entropy = 0.0

    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)

    return round(entropy, 3)


def is_hex(data: str) -> bool:
    """Check if string is hexadecimal."""
    return bool(re.fullmatch(r"[0-9a-fA-F]+", data))


def is_base64(data: str) -> bool:
    """Check if string matches Base64 charset."""
    return bool(re.fullmatch(r"[a-zA-Z0-9+/=]+", data))


def find_high_entropy_tokens(
    line: str,
    hex_threshold: float = 3.2,
    base64_threshold: float = 4.3,
    min_length: int = 16,
) -> List[Tuple[str, float]]:
    """Scan a line for tokens enclosed in quotes or assignments with suspicious entropy."""
    candidates = TOKEN_PATTERN.findall(line)
    results = []

    # Exclude common benign strings (paths, URLs without keys, typical hashes in tests)
    benign_prefixes = ("http://", "https://", "application/", "text/", "image/")

    for token in candidates:
        if any(token.startswith(b) for b in benign_prefixes):
            continue
        if len(token) < min_length:
            continue

        entropy = calculate_shannon_entropy(token)

        if is_hex(token) and len(token) >= 32 and entropy >= hex_threshold:
            results.append((token, entropy))
        elif is_base64(token) and entropy >= base64_threshold:
            results.append((token, entropy))

    return results
