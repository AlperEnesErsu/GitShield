from gitshield.core.entropy import calculate_shannon_entropy, find_high_entropy_tokens


def test_shannon_entropy_regular_words():
    # Regular english words have low entropy
    entropy = calculate_shannon_entropy("hellothisisatestword")
    assert entropy < 3.5


def test_shannon_entropy_random_secret():
    # High randomness Base64 string
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    entropy = calculate_shannon_entropy(secret)
    assert entropy > 4.5


def test_find_high_entropy_tokens():
    code_line = 'API_TOKEN = "dGhpc2lzYXZlcnlsb25ncmFuZG9tc2VjcmV0dG9rZW4xMjM="'
    tokens = find_high_entropy_tokens(code_line)
    assert len(tokens) >= 1
    assert tokens[0][0] == "dGhpc2lzYXZlcnlsb25ncmFuZG9tc2VjcmV0dG9rZW4xMjM="
