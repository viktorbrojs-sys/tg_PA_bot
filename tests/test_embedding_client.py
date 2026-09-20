import httpx
import pytest
from integrations.embedding_client import NullEmbeddingClient, OllamaEmbeddingClient


@pytest.mark.asyncio
async def test_null_embedding_client_always_returns_none():
    client = NullEmbeddingClient()
    assert await client.embed(["hello"]) is None


@pytest.mark.asyncio
async def test_ollama_client_empty_input_returns_empty_list_without_request(monkeypatch):
    async def fake_post(self, url, json=None):  # noqa: ARG001
        raise AssertionError("should not make a request for empty input")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = OllamaEmbeddingClient(base_url="http://localhost:11434", model="nomic-embed-text")

    assert await client.embed([]) == []


def _mock_embed_response(monkeypatch, payload: dict) -> None:
    async def fake_post(self, url, json=None):  # noqa: ARG001
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


@pytest.mark.asyncio
async def test_ollama_client_parses_embeddings(monkeypatch):
    _mock_embed_response(monkeypatch, {"model": "nomic-embed-text", "embeddings": [[0.1, 0.2]]})
    client = OllamaEmbeddingClient(base_url="http://localhost:11434/", model="nomic-embed-text")

    result = await client.embed(["Сдать отчёт"])
    assert result == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_ollama_client_sends_model_and_input(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None):
        captured["url"] = url
        captured["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"embeddings": [[0.1], [0.2]]}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = OllamaEmbeddingClient(base_url="http://localhost:11434", model="mxbai-embed-large")

    await client.embed(["первая", "вторая"])

    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["json"] == {"model": "mxbai-embed-large", "input": ["первая", "вторая"]}


@pytest.mark.asyncio
async def test_ollama_client_returns_none_on_http_error(monkeypatch):
    async def fake_post(self, url, json=None):  # noqa: ARG001
        raise httpx.ConnectError("boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = OllamaEmbeddingClient(base_url="http://localhost:11434", model="nomic-embed-text")

    assert await client.embed(["text"]) is None


@pytest.mark.asyncio
async def test_ollama_client_returns_none_on_malformed_payload(monkeypatch):
    _mock_embed_response(monkeypatch, {"model": "nomic-embed-text"})  # missing "embeddings"
    client = OllamaEmbeddingClient(base_url="http://localhost:11434", model="nomic-embed-text")

    assert await client.embed(["text"]) is None


@pytest.mark.asyncio
async def test_ollama_client_returns_none_on_embeddings_count_mismatch(monkeypatch):
    _mock_embed_response(monkeypatch, {"embeddings": [[0.1, 0.2]]})  # 1 vector for 2 inputs
    client = OllamaEmbeddingClient(base_url="http://localhost:11434", model="nomic-embed-text")

    assert await client.embed(["первая", "вторая"]) is None
