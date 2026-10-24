"""SSO: OpenID Connect JWTs from the client's identity provider, verified against its JWKS."""

import json
import socket
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import anyio
import httpx2
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from canon.cli import build_store
from canon.mcp_server import CallerDirectory, CanonService, ServiceConfig, build_server
from canon.mcp_server.auth import OIDCConfig, OIDCVerifier, sso_map
from canon.score import FactScoringConfig

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic"
ISSUER = "https://login.example-idp.test/tenant/v2.0"
AUDIENCE = "api://canon"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY, OTHER_KEY = _key(), _key()


def _jwks(key, kid="k1") -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}


@pytest.fixture(scope="module")
def jwks_url():
    body = json.dumps(_jwks(KEY)).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/keys"
    server.shutdown()


def _token(key=KEY, kid="k1", **claims) -> str:
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 600, **claims}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


IDENTITIES = {
    "callers": {
        "hind.legal": {"groups": ["legal"], "sso": "Hind.Alaoui@client.ma"},
        "revops.admin": {"groups": ["sales", "legal", "exec"]},
    }
}


@pytest.fixture
def verifier(jwks_url):
    config = OIDCConfig(issuer=ISSUER, audience=AUDIENCE, jwks_url=jwks_url)
    return OIDCVerifier(config, sso_map(IDENTITIES))


def test_valid_token_maps_to_the_caller(verifier):
    assert verifier.subject(_token(email="hind.alaoui@client.ma")) == "hind.legal"
    assert verifier.subject(_token(email="REVOPS.ADMIN")) == "revops.admin"


@pytest.mark.parametrize(
    "token",
    [
        _token(email="hind.alaoui@client.ma", aud="api://someone-else"),
        _token(email="hind.alaoui@client.ma", iss="https://evil.test"),
        _token(email="hind.alaoui@client.ma", exp=int(time.time()) - 3600),
        _token(key=OTHER_KEY, email="hind.alaoui@client.ma"),  # not signed by the provider
        _token(email="stranger@client.ma"),  # valid person, not in the identities file
        _token(sub="no-email-claim"),
        "not.a.jwt",
    ],
)
def test_invalid_tokens_are_refused(verifier, token):
    assert verifier.subject(token) is None


def test_unsigned_token_is_refused(verifier):
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 600,
        "email": "revops.admin",
    }
    none_alg = jwt.encode(payload, None, algorithm="none", headers={"kid": "k1"})
    assert verifier.subject(none_alg) is None


def test_mcp_over_http_with_sso_identity(jwks_url, tmp_path):
    out = tmp_path / "out"
    build_store(DATA, out, date(2026, 10, 1))
    directory = CallerDirectory.from_file(DATA / "identities.json")
    service = CanonService.from_store(
        out / "canon.sqlite",
        directory,
        ServiceConfig(facts=FactScoringConfig(as_of=date(2026, 10, 1))),
    )
    identities = json.loads((DATA / "identities.json").read_text(encoding="utf-8"))
    identities["callers"]["hind.legal"]["sso"] = "hind@client.ma"
    oidc = OIDCVerifier(OIDCConfig(ISSUER, AUDIENCE, jwks_url), sso_map(identities))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    url = f"http://127.0.0.1:{port}"
    app = build_server(service, public_url=url, oidc=oidc).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        assert httpx2.post(f"{url}/mcp", json=ping).status_code == 401
        bad = {"Authorization": f"Bearer {_token(key=OTHER_KEY, email='hind@client.ma')}"}
        assert httpx2.post(f"{url}/mcp", json=ping, headers=bad).status_code == 401

        async def go():
            headers = {"Authorization": f"Bearer {_token(email='hind@client.ma')}"}
            async with (
                httpx2.AsyncClient(headers=headers, timeout=30) as http,
                Client(streamable_http_client(f"{url}/mcp", http_client=http)) as client,
            ):
                args = {"customer": "Atlas Logistique", "caller": "revops.admin"}
                return (await client.call_tool("who_owns", args)).structured_content

        got = anyio.run(go)
        as_legal = service.who_owns("Atlas Logistique", "hind.legal").model_dump(mode="json")
        as_admin = service.who_owns("Atlas Logistique", "revops.admin").model_dump(mode="json")
        assert as_legal != as_admin
        assert got.get("owner") == as_legal.get("owner")  # identity from the SSO token
    finally:
        server.should_exit = True
        thread.join(timeout=5)
