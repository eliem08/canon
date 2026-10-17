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
