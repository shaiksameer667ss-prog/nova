from unittest.mock import MagicMock, patch

import pytest

from nova.client import ModelClient
from nova.config import get_settings


@pytest.fixture
def client():
    c = ModelClient(get_settings())
    yield c
    c.close()


def test_chat_returns_content(client):
    fake_response = MagicMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "hello"}}]
    }
    with patch.object(client._client, "post", return_value=fake_response) as post:
        result = client.chat([{"role": "user", "content": "hi"}])
    assert result == "hello"
    post.assert_called_once()


def test_chat_sends_configured_model(client):
    fake_response = MagicMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }
    with patch.object(client._client, "post", return_value=fake_response) as post:
        client.chat([{"role": "user", "content": "hi"}])
    args, kwargs = post.call_args
    assert kwargs["json"]["model"] == client.settings.model


def test_context_manager_closes():
    with ModelClient(get_settings()) as c:
        pass


def test_chat_sends_seed(client):
    fake_response = MagicMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }
    with patch.object(
        client._client, "post", return_value=fake_response
    ) as post:
        client.chat(
            [{"role": "user", "content": "hi"}],
            seed=123,
        )
    assert post.call_args.kwargs["json"]["seed"] == 123