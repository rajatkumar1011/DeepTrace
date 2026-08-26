"""Retrieval through the tracing opener, against a real TLS server.

These tests exist because of a defect that was invisible to every assertion that
looked only at DeepTrace's own code: the fetch opener was built by hand and
omitted ``HTTPErrorProcessor``. That handler is what routes a non-2xx response
into ``parent.error()``, and it is the only path by which a redirect handler is
ever reached. Without it ``open()`` returned the raw response for any status, so
a 404 body was streamed to disk, hashed, and written into the evidence store as
the traced copy — with a genuine SHA-256 and a genuine custody entry describing
something that was never the media.

A wiring assertion alone would not have caught it either, because the wiring
looked deliberate. So these tests speak HTTPS to a throwaway server on loopback
with a generated certificate, and assert on what ``fetch_public_url`` returns.

Two things are relaxed for the test, and only two: the SSRF resolver is allowed
to return loopback, and the client trusts the generated CA. Certificate
verification stays on, so a broken ``server_hostname`` in the address-pinning
code fails here rather than silently disabling TLS checks in production.
"""

import http.server
import os
import ssl
import threading
from datetime import datetime, timedelta, timezone

import pytest

# Generating a throwaway certificate needs cryptography, which arrives as a
# transitive dependency rather than a pinned one. Skipping is the honest
# outcome if it is absent — a silently-passing TLS test would be worse than
# no TLS test, since the defect these cover was invisible without a real
# transaction.
pytest.importorskip("cryptography",
                    reason="cryptography is needed to generate the test server's certificate")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from services import tracing

JPEG_BYTES = bytes.fromhex("ffd8ffe000104a46494600010100000100010000") + b"\x00" * 512 + b"\xff\xd9"


def _write_cert(directory: str) -> tuple[str, str]:
    """A throwaway self-signed certificate for ``localhost``."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = os.path.join(directory, "cert.pem")
    key_path = os.path.join(directory, "key.pem")
    with open(cert_path, "wb") as handle:
        handle.write(certificate.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))
    return cert_path, key_path


class _Routes(http.server.BaseHTTPRequestHandler):
    """A handful of responses the fetcher has to tell apart."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output readable
        pass

    def _send(self, code, body=b"", content_type=None, extra=None):
        self.send_response(code)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for header, value in (extra or {}).items():
            self.send_header(header, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/image.jpg":
            self._send(200, JPEG_BYTES, "image/jpeg")
        elif path == "/missing.jpg":
            # The shape of the original defect: an error status whose body looks
            # like a file and would hash perfectly well.
            self._send(404, b"<html>not found</html>" + b"x" * 400, "text/html")
        elif path == "/forbidden.jpg":
            self._send(403, b"denied" * 100, "text/html")
        elif path == "/login.jpg":
            self._send(200, b"<html><body>Please sign in</body></html>", "text/html")
        elif path == "/moved.jpg":
            self._send(302, b"", None, {"Location": f"https://localhost:{self.server.server_port}/image.jpg"})
        elif path == "/offsite.jpg":
            self._send(302, b"", None, {"Location": "https://127.0.0.1/secret.jpg"})
        elif path == "/empty.jpg":
            self._send(200, b"", "image/jpeg")
        elif path == "/noheader":
            self._send(200, JPEG_BYTES, None)
        else:
            self._send(404, b"?", "text/plain")


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    """A TLS server on loopback plus the CA the client should trust."""
    directory = str(tmp_path_factory.mktemp("tls"))
    cert_path, key_path = _write_cert(directory)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Routes)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_port}", cert_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def fetch(tls_server, tmp_path, monkeypatch):
    """``fetch_public_url``, pointed at the test server.

    The real ``_opener()`` is used. Only the trust anchor and the SSRF resolver
    are substituted, so the handler composition and the address pinning under
    test are the production ones.
    """
    base, cert_path = tls_server
    trust = ssl.create_default_context(cafile=cert_path)

    class _TrustingHandler(tracing._PinnedHTTPSHandler):
        def __init__(self):
            super().__init__(context=trust)

    monkeypatch.setattr(tracing, "_PinnedHTTPSHandler", _TrustingHandler)
    monkeypatch.setattr(tracing, "_resolve_public_addresses",
                        lambda host: (["127.0.0.1"], None) if host == "localhost" else ([], "blocked"))
    monkeypatch.setattr(tracing, "validate_public_url",
                        lambda url: None if url.startswith(base) else "Host is not permitted.")

    def _fetch(path):
        return tracing.fetch_public_url(f"{base}{path}", str(tmp_path))

    return _fetch


def test_a_media_response_is_preserved(fetch):
    result = fetch("/image.jpg")

    assert result["status"] == "fetched", result
    assert result["bytes"] == len(JPEG_BYTES)
    assert result["content_type"] == "image/jpeg"
    assert os.path.isfile(result["file_path"])
    assert result["file_path"].endswith(".jpg")
    assert result["redirected"] is False


def test_a_404_body_is_never_preserved_as_evidence(fetch, tmp_path):
    """The original defect. A 404 must fail, and must leave nothing on disk."""
    result = fetch("/missing.jpg")

    assert result["status"] == "failed", result
    assert "404" in result["error"]
    assert "file_path" not in result
    assert os.listdir(str(tmp_path)) == [], "an error response was written to disk"


def test_a_403_is_reported_as_a_failure_not_a_copy(fetch, tmp_path):
    result = fetch("/forbidden.jpg")

    assert result["status"] == "failed"
    assert "403" in result["error"]
    assert os.listdir(str(tmp_path)) == []


def test_an_html_page_served_with_200_is_refused(fetch, tmp_path):
    """A login wall returns 200. It is still not the media."""
    result = fetch("/login.jpg")

    assert result["status"] == "rejected", result
    assert "text/html" in result["error"]
    assert "not image, video or audio" in result["error"]
    assert os.listdir(str(tmp_path)) == []


def test_a_redirect_is_followed_and_the_final_url_recorded(fetch):
    """Redirects were unreachable before HTTPErrorProcessor was restored."""
    result = fetch("/moved.jpg")

    assert result["status"] == "fetched", result
    assert result["bytes"] == len(JPEG_BYTES)
    assert result["final_url"].endswith("/image.jpg")
    assert result["redirected"] is True


def test_a_redirect_to_a_blocked_host_is_refused(fetch, tmp_path):
    result = fetch("/offsite.jpg")

    assert result["status"] == "failed", result
    assert "disallowed" in result["error"].lower() or "blocked" in result["error"].lower()
    assert os.listdir(str(tmp_path)) == []


def test_an_empty_body_is_not_recorded_as_a_zero_byte_copy(fetch, tmp_path):
    result = fetch("/empty.jpg")

    assert result["status"] == "failed"
    assert "empty" in result["error"].lower()
    assert os.listdir(str(tmp_path)) == []


def test_a_missing_content_type_falls_back_to_the_path_extension(fetch):
    """Only when the server declared nothing — never to override a declaration."""
    result = fetch("/noheader")

    assert result["status"] == "rejected", result
    assert "no content type" in result["error"]


def test_the_opener_keeps_the_handlers_that_make_status_handling_work():
    """Guards the composition itself, independently of any transaction."""
    opener = tracing._opener()
    installed = {type(handler).__name__
                 for handlers in opener.process_response.values() for handler in handlers}

    assert "HTTPErrorProcessor" in installed, (
        "without HTTPErrorProcessor, open() returns non-2xx responses as success"
    )
    assert "default" in opener.handle_error.get("http", {}), (
        "without HTTPDefaultErrorHandler, an unhandled status never raises"
    )
    for code in (301, 302, 303, 307, 308):
        assert code in opener.handle_error.get("http", {}), f"redirect {code} unhandled"
    assert set(opener.handle_open) == {"https"}, "only https may be fetched"
