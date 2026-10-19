"""Bearer-token identity for the HTTP transport.

Each caller gets a random token; the token file stores only its SHA-256, mapped to the caller id, so
the file can be read without exposing a credential. On HTTP the caller is the token's subject and
the `caller` tool argument is ignored, so a model cannot claim someone else's access.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from mcp.server.auth.provider import AccessToken

SCOPE = "canon:read"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_tokens(path: Path) -> dict[str, str]:
    """sha256(token) -> caller id."""
    path = Path(path)
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8"))["tokens"])


def issue_token(path: Path, caller_id: str) -> str:
    """Create a token for `caller_id`, store its hash in `path`, return the token (shown once)."""
    tokens = load_tokens(path)
    token = secrets.token_urlsafe(32)
    tokens[_digest(token)] = caller_id
    Path(path).write_text(json.dumps({"tokens": tokens}, indent=2), encoding="utf-8")
    return token


def revoke_caller(path: Path, caller_id: str) -> int:
    tokens = load_tokens(path)
    kept = {h: c for h, c in tokens.items() if c != caller_id}
    Path(path).write_text(json.dumps({"tokens": kept}, indent=2), encoding="utf-8")
    return len(tokens) - len(kept)


class StaticTokenVerifier:
    """`mcp` TokenVerifier over a hashed token file (re-read on every request, so issuing or
    revoking a token takes effect without a restart)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    async def verify_token(self, token: str) -> AccessToken | None:
        digest = _digest(token)
        for known, caller_id in load_tokens(self.path).items():
            if hmac.compare_digest(known, digest):
                return AccessToken(
                    token=token, client_id=caller_id, scopes=[SCOPE], subject=caller_id
                )
        return None


# ---------------------------------------------------------------- SSO (OpenID Connect)


@dataclass(frozen=True)
class OIDCConfig:
    """Accept the client's own identity provider tokens (Entra ID, Google, Keycloak, Okta...).

    The token's signature is checked against the provider's published keys (JWKS), and its issuer,
    audience and expiry are required. `claim` names the person (default `email`); it is mapped to
    a caller through the identities file (`"sso": "omar@client.ma"` on the caller, or the caller id
    itself). Anyone not in the identities file is refused."""

    issuer: str
    audience: str
    jwks_url: str | None = (
        None  # default: discovered from <issuer>/.well-known/openid-configuration
    )
    claim: str = "email"
    algorithms: tuple[str, ...] = ("RS256", "PS256", "ES256")
    leeway_s: int = 30


def sso_map(identities: dict) -> dict[str, str]:
    """Lower-cased SSO value -> caller id, from an identities file's `callers` section."""
    out = {}
    for cid, entry in identities.get("callers", {}).items():
        values = entry.get("sso") or []
        for v in [values] if isinstance(values, str) else values:
            out[str(v).lower()] = cid
        out.setdefault(cid.lower(), cid)
    return out


class OIDCVerifier:
    """`mcp` TokenVerifier for OpenID Connect access/ID tokens (JWT)."""

    def __init__(self, config: OIDCConfig, callers: dict[str, str], jwk_client=None) -> None:
        self.config = config
        self.callers = callers
        self._jwk_client = jwk_client

    def _client(self):
        import jwt

        if self._jwk_client is None:
            url = self.config.jwks_url
            if url is None:
                import urllib.request

                discovery = self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"
                with urllib.request.urlopen(discovery, timeout=10) as r:
                    url = json.loads(r.read())["jwks_uri"]
            self._jwk_client = jwt.PyJWKClient(url, cache_keys=True)
        return self._jwk_client

    def subject(self, token: str) -> str | None:
        """The caller id this token proves, or None (bad signature, expired, wrong issuer or
        audience, or a person who is not in the identities file)."""
        import jwt

        try:
            key = self._client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self.config.algorithms),
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=self.config.leeway_s,
                options={"require": ["exp", "iss", "aud"]},
            )
        except (jwt.PyJWTError, OSError, KeyError, ValueError):
            return None
        value = claims.get(self.config.claim)
        return self.callers.get(str(value).lower()) if value else None

    async def verify_token(self, token: str) -> AccessToken | None:
        import asyncio

        caller = await asyncio.to_thread(self.subject, token)
        if caller is None:
            return None
        return AccessToken(token=token, client_id=caller, scopes=[SCOPE], subject=caller)


class ChainVerifier:
    """Static tokens first (service accounts, scripts), then SSO (people)."""

    def __init__(self, *verifiers) -> None:
        self.verifiers = [v for v in verifiers if v is not None]

    async def verify_token(self, token: str) -> AccessToken | None:
        for v in self.verifiers:
            found = await v.verify_token(token)
            if found is not None:
                return found
        return None
