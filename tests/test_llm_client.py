import httpx
import pytest
from integrations.llm_client import DEFAULT_SECTION, DeepSeekClient, NullLLMClient


@pytest.mark.asyncio
async def test_null_client_classify_always_returns_default_section():
    client = NullLLMClient()
    section = await client.classify_task("купить молоко", ["Работа", "Личное"])
    assert section == DEFAULT_SECTION


@pytest.mark.asyncio
async def test_null_client_split_into_tasks_splits_by_line():
    client = NullLLMClient()
    text = "- позвонить Иванову\n· закончить отчёт\n\nзабрать посылку"
    tasks = await client.split_into_tasks(text)
    assert tasks == ["позвонить Иванову", "закончить отчёт", "забрать посылку"]


def _mock_chat_response(monkeypatch, content: str) -> None:
    async def fake_post(self, url, headers=None, json=None):  # noqa: ARG001
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


@pytest.mark.asyncio
async def test_deepseek_classify_task_matches_known_section(monkeypatch):
    _mock_chat_response(monkeypatch, "Работа")
    client = DeepSeekClient(api_key="test-key")

    section = await client.classify_task("закончить презентацию", ["Работа", "Личное"])
    assert section == "Работа"


@pytest.mark.asyncio
async def test_deepseek_classify_task_falls_back_on_unknown_answer(monkeypatch):
    _mock_chat_response(monkeypatch, "что-то непонятное")
    client = DeepSeekClient(api_key="test-key")

    section = await client.classify_task("закончить презентацию", ["Работа", "Личное"])
    assert section == DEFAULT_SECTION


@pytest.mark.asyncio
async def test_deepseek_classify_task_falls_back_on_http_error(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):  # noqa: ARG001
        raise httpx.ConnectError("boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = DeepSeekClient(api_key="test-key")

    section = await client.classify_task("текст", ["Работа", "Личное"])
    assert section == DEFAULT_SECTION


@pytest.mark.asyncio
async def test_deepseek_split_into_tasks_parses_json_array(monkeypatch):
    _mock_chat_response(monkeypatch, '["Позвонить Иванову", "Закончить отчёт"]')
    client = DeepSeekClient(api_key="test-key")

    tasks = await client.split_into_tasks("позвони иванову и закончи отчёт")
    assert tasks == ["Позвонить Иванову", "Закончить отчёт"]


@pytest.mark.asyncio
async def test_deepseek_split_into_tasks_falls_back_on_bad_json(monkeypatch):
    _mock_chat_response(monkeypatch, "не json вообще")
    client = DeepSeekClient(api_key="test-key")

    tasks = await client.split_into_tasks("первая задача\nвторая задача")
    assert tasks == ["первая задача", "вторая задача"]
