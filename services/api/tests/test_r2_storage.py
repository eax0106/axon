import asyncio
import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.registry import ADAPTERS, VENDOR_KEYS, require
from app.providers.storage.r2 import EMPTY_SHA256, R2Storage, signature

# The examples AWS publishes for Signature Version 4 (docs: sigv4-create-canonical-request).
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # noqa: S105 - AWS's published example key
DATE = "20130524T000000Z"
NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)


def test_signature_matches_the_published_get_object_example() -> None:
    headers = {
        "host": "examplebucket.s3.amazonaws.com",
        "range": "bytes=0-9",
        "x-amz-content-sha256": EMPTY_SHA256,
        "x-amz-date": DATE,
    }
    sig, names = signature("GET", "/test.txt", {}, headers, EMPTY_SHA256, DATE, "us-east-1", SECRET)
    assert sig == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    assert names == "host;range;x-amz-content-sha256;x-amz-date"


def test_signature_matches_the_published_presigned_url_example() -> None:
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": "AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request",
        "X-Amz-Date": DATE,
        "X-Amz-Expires": "86400",
        "X-Amz-SignedHeaders": "host",
    }
    host = {"host": "examplebucket.s3.amazonaws.com"}
    sig, _ = signature(
        "GET", "/test.txt", query, host, "UNSIGNED-PAYLOAD", DATE, "us-east-1", SECRET
    )
    assert sig == "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("S3_BUCKET", "axon")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", SECRET)


def test_put_sends_a_signed_path_style_request(s3: None) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    body = b"RIFF recording"
    asyncio.run(
        R2Storage(transport=httpx.MockTransport(handler)).put(
            "recordings/c1.wav", body, "audio/wav"
        )
    )
    request = seen[0]
    assert request.method == "PUT"
    assert str(request.url) == "https://acct.r2.cloudflarestorage.com/axon/recordings/c1.wav"
    assert request.content == body and request.headers["content-type"] == "audio/wav"
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
    auth = request.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert (
        "/auto/s3/aws4_request" in auth
        and "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
    )


def test_a_rejected_upload_raises(s3: None) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(403, text="SignatureDoesNotMatch"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(R2Storage(transport=transport).put("k", b"x", "audio/wav"))


def test_health_heads_the_bucket(s3: None) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    asyncio.run(R2Storage(transport=httpx.MockTransport(handler)).health())
    assert (seen[0].method, str(seen[0].url)) == (
        "HEAD",
        "https://acct.r2.cloudflarestorage.com/axon",
    )
    assert "authorization" in seen[0].headers


def test_presigned_url_carries_its_own_credentials_and_expiry(s3: None) -> None:
    url = R2Storage().presigned_url("recordings/c 1.wav", ttl_s=600, now=NOW)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc) == ("https", "acct.r2.cloudflarestorage.com")
    assert parts.path == "/axon/recordings/c%201.wav"
    query = parse_qs(parts.query)
    assert query["X-Amz-Expires"] == ["600"] and query["X-Amz-Date"] == ["20261102T053000Z"]
    assert query["X-Amz-SignedHeaders"] == ["host"] and len(query["X-Amz-Signature"][0]) == 64
    assert query["X-Amz-Credential"] == ["AKIDEXAMPLE/20261102/auto/s3/aws4_request"]
    # Same inputs, same link; a different object, a different signature.
    assert R2Storage().presigned_url("recordings/c 1.wav", ttl_s=600, now=NOW) == url
    other = R2Storage().presigned_url("recordings/other.wav", ttl_s=600, now=NOW)
    assert parse_qs(urlsplit(other).query)["X-Amz-Signature"] != query["X-Amz-Signature"]


def test_it_is_the_registered_storage_adapter_and_503_without_keys(
    s3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ADAPTERS[(ProviderKind.STORAGE, "r2")] is R2Storage
    assert isinstance(require(ProviderKind.STORAGE), R2Storage)
    for key in VENDOR_KEYS[ProviderKind.STORAGE]["r2"]:
        monkeypatch.delenv(key)
    with pytest.raises(ProviderNotConfiguredError) as raised:
        require(ProviderKind.STORAGE)
    assert raised.value.missing_keys == list(VENDOR_KEYS[ProviderKind.STORAGE]["r2"])
