import math
import re
from collections import Counter

# Regex to extract potential secret candidate tokens (the opening quote position is captured by finditer)
TOKEN_PATTERN = re.compile(r'["\']([a-zA-Z0-9_\-\.\/+=]{16,128})["\']')

# Characters allowed in a secret candidate: standard base64, base64url and separator-style tokens
SECRET_CHARSET = re.compile(r"[A-Za-z0-9+/=_\-.]+")
HEX_PATTERN = re.compile(r"[0-9a-fA-F]+")
UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# Identifier-like dotted names (com.example.service) without digits
DOTTED_IDENTIFIER = re.compile(r"[A-Za-z_]+(?:\.[A-Za-z_]+)+")
VERSION_PATTERN = re.compile(r"v?\d+(?:\.\d+)+(?:[-+][\w.]+)?")
PATH_SEGMENT = re.compile(r"[A-Za-z0-9_\-.]+")
# Words in camelCase / PascalCase identifiers: "systemInstruction" -> system, Instruction
CAMEL_WORD = re.compile(r"[A-Z]{2,}(?![a-z])|[A-Z]?[a-z]{2,}")
SEPARATOR_SPLIT = re.compile(r"[_\-.]")
SHORT_NUMBER = re.compile(r"[0-9]{1,4}")
WORD_SEGMENT = re.compile(r"[A-Za-z]+")
LOWER_WORD_SEGMENT = re.compile(r"[a-z_\-.]+")
CAPITALIZED_WORD = re.compile(r"[A-Z][a-z]{2,}")
FILE_EXTENSION = re.compile(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,6}")
# Text before a quoted value that names a secret-ish variable, key or header
SECRET_CONTEXT = re.compile(
    r"(?i)(?:secret|token|key|passw(?:or)?d|pwd|auth|credential)[\w.\-]*[\"']?[\])]?\s*(?:[:=]|\()\s*$"
)
BENIGN_PREFIXES = ("http://", "https://", "application/", "text/", "image/")
# Length-normalisation factor: a random string of length n rarely reaches 100% of log2(n)
LENGTH_FACTOR = 0.8


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
    return bool(HEX_PATTERN.fullmatch(data))


def is_base64(data: str) -> bool:
    """Check if string matches the secret charset (Base64, Base64url and separator-style tokens)."""
    return bool(SECRET_CHARSET.fullmatch(data))


def _has_secret_context(prefix: str) -> bool:
    """True when the text before a quoted value names a secret-ish key (api_key = ", "token": ")."""
    return bool(SECRET_CONTEXT.search(prefix))


def _char_class_count(token: str) -> int:
    return sum(
        (
            any(c.islower() for c in token),
            any(c.isupper() for c in token),
            any(c.isdigit() for c in token),
        )
    )


def _is_sequential_or_repetitive(token: str) -> bool:
    lowered = token.lower()
    if len(set(lowered)) < 4:
        return True
    ascending = sum(1 for a, b in zip(lowered, lowered[1:], strict=False) if ord(b) - ord(a) == 1)
    return ascending >= 0.5 * (len(lowered) - 1)


def _looks_like_path(token: str) -> bool:
    if "/" not in token:
        return False
    segments = [s for s in token.split("/") if s]
    if len(segments) < 2 or not all(PATH_SEGMENT.fullmatch(s) for s in segments):
        return False
    if FILE_EXTENSION.fullmatch(segments[-1]):
        return True
    # Module paths without an extension: "../components/DiffOverview", "@/lib/apiClient".
    return all(s in (".", "..") or LOWER_WORD_SEGMENT.fullmatch(s) or CAPITALIZED_WORD.fullmatch(s)
               or _is_word_identifier(s) for s in segments)


def _is_word_identifier(token: str) -> bool:
    """Identifier names made of dictionary-like words: camelCase or separator-style (SNAKE, KEBAB).

    Real secrets are random, so they rarely split into words; a digit inside a word disqualifies it.
    """
    words = CAMEL_WORD.findall(token)
    if len(words) >= 2 and "".join(words) == token:
        return True
    parts = SEPARATOR_SPLIT.split(token)
    if len(parts) < 2 or not all(parts):
        return False
    if not all(WORD_SEGMENT.fullmatch(p) or SHORT_NUMBER.fullmatch(p) for p in parts):
        return False
    return any(WORD_SEGMENT.fullmatch(p) for p in parts)


def _is_benign(token: str) -> bool:
    """Tokens that look random but are known non-secret shapes (hashes, UUIDs, paths, versions)."""
    if token.startswith(BENIGN_PREFIXES):
        return True
    if UUID_PATTERN.fullmatch(token):
        return True
    if _looks_like_path(token):
        return True
    if DOTTED_IDENTIFIER.fullmatch(token) or VERSION_PATTERN.fullmatch(token):
        return True
    if _is_word_identifier(token):
        return True
    return _is_sequential_or_repetitive(token)


def _length_threshold(length: int, base_threshold: float) -> float:
    """Entropy a token of this length can realistically reach, capped at the base threshold."""
    return min(base_threshold, LENGTH_FACTOR * math.log2(length))


def find_high_entropy_tokens(
    line: str,
    hex_threshold: float = 3.2,
    base64_threshold: float = 4.3,
    min_length: int = 16,
) -> list[tuple[str, float]]:
    """Scan a line for quoted tokens with suspicious entropy.

    Pure hex tokens (git SHAs, SHA-256 digests) are only reported when the assignment names a
    secret-ish key. Tokens must mix at least two character classes (upper/lower/digit).
    """
    results: list[tuple[str, float]] = []
    seen = set()

    for match in TOKEN_PATTERN.finditer(line):
        token = match.group(1)
        if token in seen or len(token) < min_length:
            continue
        seen.add(token)

        if _is_benign(token) or _char_class_count(token) < 2:
            continue

        if is_hex(token):
            # Hashes are everywhere in real code; only treat them as secrets in secret-ish assignments
            if not _has_secret_context(line[: match.start()]):
                continue
            threshold = _length_threshold(len(token), hex_threshold)
        elif is_base64(token):
            threshold = _length_threshold(len(token), base64_threshold)
        else:
            continue

        entropy = calculate_shannon_entropy(token)
        if entropy >= threshold:
            results.append((token, entropy))

    return results
