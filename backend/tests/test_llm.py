import pytest
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app import llm
from app.config import get_settings
from app.fake_model import ScriptedChatModel


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    get_settings.cache_clear()
    llm._build.cache_clear()
    yield
    get_settings.cache_clear()
    llm._build.cache_clear()


def test_builds_each_provider_with_thinking(env):
    ollama = llm.build_chat_model("ollama:qwen3:0.6b", thinking=True)
    assert isinstance(ollama, ChatOllama) and ollama.model == "qwen3:0.6b" and ollama.reasoning
    assert llm.build_chat_model("ollama:qwen3:0.6b").reasoning is False
    assert llm.build_chat_model("ollama:qwen3:0.6b") is llm.build_chat_model("ollama:qwen3:0.6b")

    openai = llm.build_chat_model("openai:gpt-5-mini", thinking=True)
    assert isinstance(openai, ChatOpenAI) and openai.reasoning == {
        "effort": "medium",
        "summary": "auto",
    }
    anthropic = llm.build_chat_model("anthropic:claude-sonnet-5-5", thinking=True)
    assert isinstance(anthropic, ChatAnthropic) and anthropic.thinking["type"] == "enabled"
    assert anthropic.max_tokens > anthropic.thinking["budget_tokens"]
    assert isinstance(llm.build_chat_model("fake:echo"), ScriptedChatModel)


def test_missing_keys_and_bad_ids(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    llm._build.cache_clear()
    with pytest.raises(llm.ModelError, match="OPENAI_API_KEY"):
        llm.build_chat_model("openai:gpt-5")
    for bad in ("gpt-5", "bogus:x", "ollama:"):
        with pytest.raises(llm.ModelError):
            llm.split_model_id(bad)
    get_settings.cache_clear()
