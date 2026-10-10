import pytest

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


def _tokens(line):
    return [token for token, _ in find_high_entropy_tokens(line)]


def test_stripe_style_underscore_token_is_evaluated():
    key = "sk_live_" + "51HxQ2bLkd8sJ2mN4pQ7rT9vW1yZ3aB5cD"
    assert key in _tokens(f'key = "{key}"')


def test_base64url_token_is_evaluated():
    token = "aB3-dE5_gH7-jK9_mN2-pQ4_rS6"
    assert token in _tokens(f'secret = "{token}"')


def test_random_16_to_18_char_secret_in_api_key_context_is_caught():
    assert _tokens('api_key = "aB3dE5gH7jK9mN2p"') == ["aB3dE5gH7jK9mN2p"]
    assert _tokens('api_key = "Xk9Lm2Pq8Rt4Vw7Yz1"') == ["Xk9Lm2Pq8Rt4Vw7Yz1"]
    assert _tokens('api_key = "Xk9Lm2Pq8Rt4Vw7Yz1Ab"') == ["Xk9Lm2Pq8Rt4Vw7Yz1Ab"]


def test_git_sha1_not_flagged_without_secret_context():
    assert _tokens('commit = "9fceb02d0ae598e95dc970b74767f19372d61af8"') == []


def test_git_sha1_not_flagged_even_with_innocent_key_name():
    assert _tokens('sha = "9fceb02d0ae598e95dc970b74767f19372d61af8"') == []


def test_sha256_not_flagged_without_secret_context():
    digest = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    assert _tokens(f'checksum = "{digest}"') == []


def test_pure_hex_reported_in_secret_context():
    digest = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    assert _tokens(f'token = "{digest}"') == [digest]


def test_uuid_not_flagged():
    assert _tokens('id = "123e4567-e89b-12d3-a456-426614174000"') == []
    assert _tokens('api_token = "123e4567-e89b-12d3-a456-426614174000"') == []


def test_file_path_not_flagged():
    assert _tokens('path = "src/utils/helpers.py"') == []
    assert _tokens('path = "config/settings/production_settings"') == []


def test_dotted_identifier_not_flagged():
    assert _tokens('pkg = "com.example.service.handler"') == []


def test_version_string_not_flagged():
    assert _tokens('version = "1.2.3.4.5.6.7.8.9.10.11"') == []


def test_repeated_and_sequential_patterns_not_flagged():
    assert _tokens('token = "aaaaaaaaaaaaaaaaaaaaaaaa"') == []
    assert _tokens('token = "0123456789abcdefABCDEF"') == []


def test_lowercase_identifier_not_flagged():
    assert _tokens('msg = "some_long_variable_name_here"') == []


def test_length_aware_threshold_allows_16_char_random_secret():
    # Max entropy of 16 distinct characters is log2(16) = 4.0, which the old fixed 4.3 threshold could never reach
    assert len(_tokens('api_key = "aB3dE5gH7jK9mN2p"')) == 1


def test_duplicate_tokens_on_one_line_reported_once():
    token = "aB3dE5gH7jK9mN2pQ4rS"
    assert _tokens(f'a = "{token}"; b = "{token}"') == [token]


@pytest.mark.parametrize(
    "identifier",
    ["systemInstruction", "primaryLocationLineHash", "ENTROPY-HIGH-001", "SEC-SENDGRID-017"],
)
def test_identifier_like_names_are_not_flagged(identifier):
    # Regression: found by running GitShield on its own diff
    assert _tokens(f'x = "{identifier}"') == []


def test_random_separator_secrets_still_caught_after_identifier_rule():
    assert _tokens('blob = "aB3_dE5gH7_jK9mN2p"') == ["aB3_dE5gH7_jK9mN2p"]
    assert _tokens('blob = "Xk9-Lm2Pq8-Rt4Vw7Yz1"') == ["Xk9-Lm2Pq8-Rt4Vw7Yz1"]
