from esperanto import AIFactory, LanguageModel
from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger

from open_notebook.ai.models import model_manager
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import token_count


def _amalia_from_env(**kwargs) -> LanguageModel:
    """Build the fallback AMALIA language model directly from env vars (no DB).

    The model can run locally — served either through an OpenAI-compatible
    endpoint (vLLM / TGI / the in-house AMALIA host) or through Ollama. The
    provider is chosen, first match wins:

      1. explicit ``AMALIA_PROVIDER`` = ``openai-compatible`` | ``ollama``
      2. the scheme of ``AMALIA_SMART_LLM`` (e.g. ``ollama:llama3`` -> ollama)
      3. ``openai-compatible`` (default — the AMALIA host)
    """
    import os

    # AMALIA_SMART_LLM is "<scheme>:<model>", e.g. "openai:carminho/AMALIA-9B-50-DPO"
    # or "ollama:qwen3:8b". Keep the full model name after the first ':'.
    smart_llm = os.environ.get("AMALIA_SMART_LLM", "openai:carminho/AMALIA-9B-50-DPO")
    scheme, sep, rest = smart_llm.partition(":")
    model_name = rest if sep else smart_llm

    provider = os.environ.get("AMALIA_PROVIDER", "").strip().lower()
    if not provider:
        provider = "ollama" if scheme.strip().lower() == "ollama" else "openai-compatible"

    if provider == "ollama":
        # Esperanto's ollama provider already falls back to OLLAMA_BASE_URL /
        # OLLAMA_API_BASE, but pass base_url explicitly when set so the target
        # is unambiguous (e.g. the bundled `ollama` container on marinha-net).
        base_url = os.environ.get("OLLAMA_API_BASE") or os.environ.get("OLLAMA_BASE_URL")
        config = {**kwargs}
        if base_url:
            config["base_url"] = base_url.rstrip("/")
        return AIFactory.create_language(
            model_name=model_name, provider="ollama", config=config
        )

    # Default: OpenAI-compatible endpoint (vLLM / TGI / AMALIA host).
    base_url = os.environ.get("AMALIA_BASE_URL", "https://api.novasearch.org/amalia-llm/v1")
    api_key = os.environ.get("AMALIA_API_KEY", "dummy")
    return AIFactory.create_language(
        model_name=model_name,
        provider="openai-compatible",
        config={"base_url": base_url, "api_key": api_key, **kwargs},
    )


async def provision_langchain_model(
    content, model_id, default_type, **kwargs
) -> BaseChatModel:
    """
    Returns the best model to use based on the context size and on whether there is a specific model being requested in Config.
    If context > 105_000, returns the large_context_model
    If model_id is specified in Config, returns that model
    Otherwise, returns the default model for the given type
    """
    tokens = token_count(content)
    model = None
    selection_reason = ""

    if tokens > 105_000:
        selection_reason = f"large_context (content has {tokens} tokens)"
        logger.debug(
            f"Using large context model because the content has {tokens} tokens"
        )
        model = await model_manager.get_default_model("large_context", **kwargs)
    elif model_id:
        selection_reason = f"explicit model_id={model_id}"
        model = await model_manager.get_model(model_id, **kwargs)
    else:
        selection_reason = f"default for type={default_type}"
        model = await model_manager.get_default_model(default_type, **kwargs)

    logger.debug(f"Using model: {model}")

    if model is None:
        # No DB model configured — fall back to AMALIA from env vars.
        try:
            model = _amalia_from_env(**kwargs)
            logger.info(
                f"No DB model for '{selection_reason}' — falling back to AMALIA from env vars"
            )
        except Exception as e:
            logger.error(f"AMALIA env fallback failed: {e}")
            raise ConfigurationError(
                f"No model configured for {selection_reason} and AMALIA fallback failed. "
                f"Check AMALIA_BASE_URL / AMALIA_API_KEY in .env."
            ) from e

    if not isinstance(model, LanguageModel):
        logger.error(
            f"Model type mismatch: Expected LanguageModel but got {type(model).__name__}. "
            f"Selection reason: {selection_reason}. "
            f"model_id={model_id}, default_type={default_type}."
        )
        raise ConfigurationError(
            f"Model is not a LanguageModel: {model}. "
            f"Please check that the model configured for '{default_type}' is a language model, not an embedding or speech model."
        )

    return model.to_langchain()
