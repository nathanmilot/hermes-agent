"""API key and model resolution from Hermes config.

Resolves API credentials and model endpoints from the active Hermes provider
config, so the GEPA evaluator can use the same API access as the agent itself.
"""
import os
import sys
from typing import Optional


def resolve_api_config() -> dict:
    """Read API credentials from Hermes config.

    Returns a dict with keys suitable for litellm:
        api_key, api_base, model_name, provider_name
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from hermes_cli.config import load_config
    except ImportError:
        return {}

    cfg = load_config()
    model_cfg = cfg.get("model", {})

    provider_name = model_cfg.get("provider", "")
    model_name = model_cfg.get("default", "")
    api_base = model_cfg.get("base_url", "")

    # Resolve API key from environment
    # Hermes stores keys in env vars set by the gateway/CLI at startup
    api_key = ""

    # Try common env var patterns
    if provider_name == "opencode-go":
        api_key = os.environ.get("OPENCODE_GO_API_KEY", "")
    elif provider_name == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
    elif provider_name == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    elif provider_name == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
    elif provider_name == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # Fallback: try loading from .env directly
    if not api_key:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip().strip('"').strip("'")
                        if k == "OPENCODE_GO_API_KEY" and not api_key:
                            api_key = v
                        elif k == "OPENROUTER_API_KEY" and not api_key:
                            api_key = v

    return {
        "api_key": api_key,
        "api_base": api_base,
        "model_name": model_name,
        "provider_name": provider_name,
    }


def make_hermes_litellm_judge(verbose: bool = False):
    """Create a judge function that routes through the Hermes provider.

    Reads the active provider from hermes config and creates a litellm-compatible
    judge using the same API key and endpoint the agent uses.
    """
    import litellm

    config = resolve_api_config()
    api_key = config["api_key"]
    api_base = config["api_base"]
    model_name = config["model_name"]
    provider_name = config["provider_name"]

    if not api_key:
        if verbose:
            print(f"  WARNING: No API key found for provider '{provider_name}'")
            print(f"  Set {provider_name.upper()}_API_KEY or OPENCODE_GO_API_KEY in ~/.hermes/.env")
            print(f"  Or pass --api-key to the runner")

    if verbose and api_base:
        print(f"  Provider: {provider_name}, model: {model_name}, base: {api_base}")

    # Map model name to litellm format based on provider
    if provider_name == "opencode-go":
        # OpenCode Go uses OpenAI-compatible API with custom models
        litellm_model = f"openai/{model_name}"
    elif provider_name == "openrouter":
        litellm_model = f"openrouter/{model_name}"
    else:
        litellm_model = model_name

    def judge(messages: list[dict]) -> str:
        # deepseek-v4-pro silently drops content when system messages are present.
        # Merge system message into user message as a prefix instead.
        system_content = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_content += m["content"] + "\n\n"
            else:
                user_messages.append(m)
        
        if system_content and user_messages:
            # Prepend system content to first user message
            user_messages[0] = {
                "role": "user",
                "content": system_content + user_messages[0]["content"],
            }
        
        kwargs = {
            "model": litellm_model,
            "messages": user_messages if user_messages else messages,
            "temperature": 0.0,
            "max_tokens": 800,  # deepseek-v4-pro reasoning model needs headroom
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content or ""

    return judge


def make_hermes_reflection_lm(verbose: bool = False):
    """Create a GEPA-compatible reflection LM callable using Hermes provider.
    
    Returns a callable suitable for GEPA's `reflection_lm` parameter.
    Uses the same API key and endpoint as the active Hermes provider,
    with higher max_tokens since reflection prompts are longer than judge calls.
    """
    import litellm

    config = resolve_api_config()
    api_key = config["api_key"]
    api_base = config["api_base"]
    model_name = config["model_name"]
    provider_name = config["provider_name"]

    if not api_key:
        if verbose:
            print(f"  WARNING: No API key for reflection LM (provider={provider_name})")
        return None

    # Map to litellm format
    if provider_name == "opencode-go":
        litellm_model = f"openai/{model_name}"
    elif provider_name == "openrouter":
        litellm_model = f"openrouter/{model_name}"
    else:
        litellm_model = model_name

    if verbose:
        print(f"  Reflection LM: {litellm_model} via {api_base}")

    def reflection_lm(prompt) -> str:
        """GEPA-compatible reflection callable.
        
        GEPA passes either a str or list[dict] for the prompt.
        """
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = list(prompt)  # copy to avoid mutating input
        
        # deepseek-v4-pro silently drops content with system messages.
        # Merge system content into first user message.
        system_content = ""
        user_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_content += m.get("content", "") + "\n\n"
            else:
                user_messages.append(m)
        
        if system_content and user_messages:
            user_messages[0] = {
                "role": "user",
                "content": system_content + user_messages[0].get("content", ""),
            }
            messages = user_messages

        kwargs = {
            "model": litellm_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 4000,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content or ""

    return reflection_lm
