from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SALT = b"saltysalt"
IV = b" " * 16
PEANUTS = b"peanuts"
CHROME_EPOCH_OFFSET = 11644473600
DOMAINS = ("chatgpt.com", "openai.com")
BROWSERS = {
    "brave": "BraveSoftware/Brave-Browser",
    "chrome": "google-chrome",
    "chromium": "chromium",
    "edge": "microsoft-edge",
    "vivaldi": "vivaldi",
}
KEYRING_APP = {
    "brave": "brave",
    "chrome": "chrome",
    "chromium": "chromium",
    "edge": "microsoft-edge",
    "vivaldi": "vivaldi",
}
SAME_SITE = {0: "None", 1: "Lax", 2: "Strict"}


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str
    expires: float
    secure: bool
    http_only: bool
    same_site: str | None

    def to_playwright(self) -> dict:
        cookie = {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "secure": self.secure,
            "httpOnly": self.http_only,
        }
        if self.same_site and not (self.same_site == "None" and not self.secure):
            cookie["sameSite"] = self.same_site
        return cookie


def derive_key(password: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=SALT, iterations=1).derive(password)


def decrypt_value(encrypted: bytes, keys: list[bytes]) -> str:
    if not encrypted:
        return ""
    prefix = encrypted[:3]
    if prefix not in (b"v10", b"v11"):
        return encrypted.decode(errors="replace")
    payload = encrypted[3:]
    if not payload or len(payload) % 16:
        raise ValueError("invalid ciphertext")
    best = ""
    best_score = 0.0
    for key in keys:
        try:
            decryptor = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
            data = decryptor.update(payload) + decryptor.finalize()
        except Exception:
            continue
        if data and 1 <= data[-1] <= 16:
            data = data[: -data[-1]]
        for strip in (0, 16, 32):
            candidate = _trim_non_printable(data[strip:])
            if not candidate:
                continue
            score = sum(1 for byte in candidate if 32 <= byte < 127) / len(candidate)
            if score > best_score or (score == best_score and len(candidate) > len(best)):
                best = candidate.decode(errors="replace")
                best_score = score
    if best_score < 0.9:
        raise ValueError("could not decrypt cookie")
    return best


def _trim_non_printable(data: bytes) -> bytes:
    start = 0
    while start < len(data) and not 32 <= data[start] < 127:
        start += 1
    end = len(data)
    while end > start and not 32 <= data[end - 1] < 127:
        end -= 1
    return data[start:end]


def keyring_password(app: str) -> bytes | None:
    if shutil.which("secret-tool") is None:
        return None
    try:
        proc = subprocess.run(
            [
                "secret-tool",
                "lookup",
                "xdg:schema",
                "chrome_libsecret_os_crypt_password_v2",
                "application",
                KEYRING_APP.get(app, app),
            ],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.rstrip(b"\n") or None


def find_sources(browser: str | None = None) -> list[tuple[str, Path]]:
    names = [browser] if browser else list(BROWSERS)
    sources: list[tuple[str, Path]] = []
    for name in names:
        rel = BROWSERS.get(name)
        if rel is None:
            continue
        for profile in ("Default", "Profile 1"):
            base = Path.home() / ".config" / rel / profile
            if (base / "Cookies").exists():
                sources.append((name, base))
    return sources


def _query_cookies(profile: Path) -> list[tuple]:
    tmp = Path(tempfile.mkdtemp(prefix="benedict-cookies-"))
    try:
        for name in ("Cookies", "Cookies-wal", "Cookies-shm"):
            src = profile / name
            if src.exists():
                shutil.copy(src, tmp / name)
        con = sqlite3.connect(f"file:{tmp / 'Cookies'}?mode=ro", uri=True)
        try:
            columns = {row[1] for row in con.execute("PRAGMA table_info(cookies)")}
            secure = "is_secure" if "is_secure" in columns else "secure"
            http_only = "is_httponly" if "is_httponly" in columns else "httponly"
            same = next((c for c in ("samesite", "same_site") if c in columns), None)
            partition = "partition_key" if "partition_key" in columns else None
            select = [
                "host_key",
                "name",
                "encrypted_value",
                "path",
                "expires_utc",
                secure,
                http_only,
                same or "NULL",
                partition or "NULL",
            ]
            return con.execute(f"SELECT {', '.join(select)} FROM cookies").fetchall()
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_cookies(profile: Path, browser: str) -> list[Cookie]:
    keys: list[bytes] = []
    secret = keyring_password(browser)
    if secret:
        keys.append(derive_key(secret))
    keys.append(derive_key(PEANUTS))
    found: dict[tuple[str, str, str], Cookie] = {}
    rows = _query_cookies(profile)
    for host, name, encrypted, path, expires, secure, http_only, same_site, partition in rows:
        if not any(host == d or host.endswith("." + d) for d in DOMAINS):
            continue
        if partition:
            continue
        encrypted = bytes(encrypted) if encrypted else b""
        try:
            value = decrypt_value(encrypted, keys)
        except ValueError:
            continue
        if not value:
            continue
        expires_at = -1.0 if not expires else expires / 1_000_000 - CHROME_EPOCH_OFFSET
        if expires_at != -1 and expires_at < time.time():
            continue
        cookie = Cookie(
            name=name,
            value=value,
            domain=host,
            path=path or "/",
            expires=expires_at,
            secure=bool(secure),
            http_only=bool(http_only),
            same_site=SAME_SITE.get(same_site) if same_site is not None else None,
        )
        found[(host, name, cookie.path)] = cookie
    return list(found.values())


def has_session(cookies: list[Cookie]) -> bool:
    return any(c.name.startswith("__Secure-next-auth.session-token") for c in cookies)
