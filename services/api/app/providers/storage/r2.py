"""S3-compatible object storage (Cloudflare R2, or any S3 store) with AWS Signature V4.

Path-style addressing: {S3_ENDPOINT_URL}/{S3_BUCKET}/{key}. Signing is done here with the
standard library (no SDK): `signature()` is the V4 algorithm, checked in the tests against the
examples AWS publishes.
"""

import hashlib
import hmac
import os
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx

from app.providers.base import ObjectStorageProvider

TIMEOUT_S = 60.0
ALGORITHM = "AWS4-HMAC-SHA256"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _uri(path: str) -> str:
    return quote(path, safe="/~")


def _query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items())
    )


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def signature(
    method: str,
    path: str,
    query: dict[str, str],
    headers: dict[str, str],
    payload_hash: str,
    amz_date: str,
    region: str,
    secret_key: str,
) -> tuple[str, str]:
    """(signature, signed header names) for a request. `headers` are the ones to sign, any case."""
    lowered = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    names = ";".join(sorted(lowered))
    canonical_headers = "".join(f"{k}:{lowered[k]}\n" for k in sorted(lowered))
    canonical = "\n".join(
        [method, _uri(path), _query(query), canonical_headers, names, payload_hash]
    )
    scope = f"{amz_date[:8]}/{region}/s3/aws4_request"
    to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = _hmac(("AWS4" + secret_key).encode(), amz_date[:8])
    for part in (region, "s3", "aws4_request"):
        key = _hmac(key, part)
    return hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest(), names


class R2Storage(ObjectStorageProvider):
    name = "r2"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    # -- configuration -------------------------------------------------------------------
    def _config(self) -> tuple[str, str, str, str, str]:
        endpoint = os.environ["S3_ENDPOINT_URL"].rstrip("/")
        region = os.environ.get("S3_REGION") or "auto"
        return (
            endpoint,
            os.environ["S3_BUCKET"],
            os.environ["S3_ACCESS_KEY_ID"],
            os.environ["S3_SECRET_ACCESS_KEY"],
            region,
        )

    def _target(self, key: str = "") -> tuple[str, str, str]:
        """(scheme and host, host, path) of the bucket, or of one object in it."""
        endpoint, bucket, *_ = self._config()
        parts = urlsplit(endpoint)
        path = (
            f"{parts.path}/{bucket}/{key}".replace("//", "/").rstrip("/")
            if key
            else f"{parts.path}/{bucket}"
        )
        return f"{parts.scheme}://{parts.netloc}", parts.netloc, path

    # -- requests ------------------------------------------------------------------------
    def _signed_headers(
        self, method: str, path: str, host: str, payload_hash: str, now: datetime
    ) -> dict[str, str]:
        _, _, access, secret, region = self._config()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        signed = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        sig, names = signature(method, path, {}, signed, payload_hash, amz_date, region, secret)
        scope = f"{amz_date[:8]}/{region}/s3/aws4_request"
        auth = f"{ALGORITHM} Credential={access}/{scope}, SignedHeaders={names}, Signature={sig}"
        return {"Authorization": auth, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        endpoint, host, path = self._target(key)
        headers = self._signed_headers(
            "PUT", path, host, hashlib.sha256(data).hexdigest(), datetime.now(UTC)
        )
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
            response = await client.put(
                endpoint + _uri(path),
                content=data,
                headers={**headers, "Content-Type": content_type},
            )
            response.raise_for_status()

    async def health(self) -> None:
        endpoint, host, path = self._target()
        headers = self._signed_headers("HEAD", path, host, EMPTY_SHA256, datetime.now(UTC))
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
            response = await client.head(endpoint + _uri(path), headers=headers)
            response.raise_for_status()

    def presigned_url(self, key: str, ttl_s: int = 900, now: datetime | None = None) -> str:
        """A link that reads this object for `ttl_s` seconds without any credentials."""
        endpoint, host, path = self._target(key)
        _, _, access, secret, region = self._config()
        amz_date = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        scope = f"{amz_date[:8]}/{region}/s3/aws4_request"
        query = {
            "X-Amz-Algorithm": ALGORITHM,
            "X-Amz-Credential": f"{access}/{scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(ttl_s),
            "X-Amz-SignedHeaders": "host",
        }
        sig, _ = signature(
            "GET", path, query, {"host": host}, "UNSIGNED-PAYLOAD", amz_date, region, secret
        )
        return f"{endpoint}{_uri(path)}?{_query(query)}&X-Amz-Signature={sig}"
