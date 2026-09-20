import sqlite3
import time

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from benedict.cookieimport import (
    CHROME_EPOCH_OFFSET,
    IV,
    decrypt_value,
    derive_key,
    has_session,
    load_cookies,
)


def encrypt(value: str, key: bytes, prefix: bytes = b"v11") -> bytes:
    padder = padding.PKCS7(128).padder()
    data = padder.update(value.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(IV)).encryptor()
    return prefix + encryptor.update(data) + encryptor.finalize()


def make_db(tmp_path, rows):
    db = tmp_path / "Cookies"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE cookies (
            host_key TEXT, name TEXT, encrypted_value BLOB, path TEXT,
            expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER,
            samesite INTEGER, partition_key TEXT, value TEXT
        )
        """
    )
    con.executemany("INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return tmp_path


def test_decrypt_roundtrip():
    key = derive_key(b"peanuts")
    assert decrypt_value(encrypt("hello world", key), [key]) == "hello world"


def test_decrypt_plaintext():
    assert decrypt_value(b"plain", [derive_key(b"peanuts")]) == "plain"


def test_decrypt_strips_prefix():
    key = derive_key(b"peanuts")
    blob = encrypt("\x00" * 16 + "realvalue", key)
    assert decrypt_value(blob, [key]) == "realvalue"


def test_decrypt_wrong_key_rejected():
    import pytest

    key = derive_key(b"peanuts")
    with pytest.raises(ValueError):
        decrypt_value(encrypt("hello world", key), [derive_key(b"other-password")])


def test_load_cookies(tmp_path):
    key = derive_key(b"peanuts")
    live = int((time.time() + 3600 + CHROME_EPOCH_OFFSET) * 1_000_000)
    rows = [
        (
            ".chatgpt.com",
            "__Secure-next-auth.session-token.0",
            encrypt("token-value", key),
            "/",
            live,
            1,
            1,
            1,
            "",
            "",
        ),
        ("example.com", "other", encrypt("x", key), "/", live, 1, 1, 1, "", ""),
        (".chatgpt.com", "expired", encrypt("x", key), "/", 1, 1, 1, 1, "", ""),
        (
            ".chatgpt.com",
            "partitioned",
            encrypt("x", key),
            "/",
            live,
            1,
            1,
            1,
            "https://chatgpt.com",
            "",
        ),
    ]
    cookies = load_cookies(make_db(tmp_path, rows), "brave")
    names = {c.name for c in cookies}
    assert names == {"__Secure-next-auth.session-token.0"}
    assert has_session(cookies)
    playwright_cookie = cookies[0].to_playwright()
    assert playwright_cookie["domain"] == ".chatgpt.com"
    assert playwright_cookie["secure"] is True
    assert playwright_cookie["httpOnly"] is True
    assert playwright_cookie["sameSite"] == "Lax"
    assert playwright_cookie["expires"] > time.time()


def test_load_cookies_session_expiry(tmp_path):
    key = derive_key(b"peanuts")
    rows = [
        (".openai.com", "session", encrypt("x", key), "/", 0, 1, 0, -1, "", ""),
    ]
    cookies = load_cookies(make_db(tmp_path, rows), "brave")
    assert cookies[0].expires == -1
    assert cookies[0].same_site is None
