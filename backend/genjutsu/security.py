import base64
import hashlib
import hmac
import ipaddress
import socket
import time
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def cipher(secret: str):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def sign_asset(secret: str, asset_id: str, expires: int):
    return hmac.new(
        secret.encode(), f"asset:{asset_id}:{expires}".encode(), hashlib.sha256
    ).hexdigest()


def valid_asset_signature(secret, asset_id, expires, token):
    return (
        expires >= int(time.time())
        and expires <= int(time.time()) + 86400
        and hmac.compare_digest(sign_asset(secret, asset_id, expires), token)
    )


def allowed_remote(url: str, settings, *, custom=False, download=False, upload=False):
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise ValueError("Invalid remote URL")
    if settings.testing:
        return url
    if parsed.scheme != "https":
        raise ValueError("Remote APIs and result URLs require HTTPS")
    if custom:
        if url.rstrip("/") not in {x.rstrip("/") for x in settings.custom_api_urls}:
            raise ValueError("API endpoint is not approved by the operator")
    elif download or upload:
        if not any(
            parsed.hostname == host or parsed.hostname.endswith("." + host)
            for host in (settings.upload_hosts if upload else settings.download_hosts)
        ):
            raise ValueError("Result host is not approved by the operator")
    else:
        hosts = {urlsplit(x).hostname for x in settings.provider_base_urls.values()}
        hosts.update(urlsplit(x).hostname for x in settings.custom_api_urls)
        if parsed.hostname not in hosts:
            raise ValueError("Provider URL host is not approved")
    addresses = socket.getaddrinfo(
        parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
    )
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise ValueError("Private and reserved addresses are not allowed")
    return url


class EncryptedPayloadCodec(PayloadCodec):
    def __init__(self, secret):
        self.fernet = cipher(secret)

    async def encode(self, payloads):
        return [
            Payload(
                metadata={"encoding": b"binary/genjutsu-encrypted-v1"},
                data=self.fernet.encrypt(p.SerializeToString()),
            )
            for p in payloads
        ]

    async def decode(self, payloads):
        result = []
        for p in payloads:
            if p.metadata.get("encoding") == b"binary/genjutsu-encrypted-v1":
                result.append(Payload.FromString(self.fernet.decrypt(p.data)))
            else:
                result.append(p)
        return result
