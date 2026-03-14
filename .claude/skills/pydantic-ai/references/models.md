# Model Providers — Deep Reference

## Model Identifier Format

`'provider:model-name'` — e.g., `'openai:gpt-5.2'`

## Supported Providers

### First-Party Support

| Provider | Prefix | Example | Install Extra |
|---|---|---|---|
| OpenAI | `openai:` | `openai:gpt-5.2` | included |
| Anthropic | `anthropic:` | `anthropic:claude-sonnet-4-6` | `[anthropic]` |
| Google (Gemini) | `google:` | `google:gemini-3-flash-preview` | `[google]` |
| DeepSeek | `deepseek:` | `deepseek:deepseek-chat` | uses OpenAI compat |
| Grok (xAI) | `grok:` | `grok:grok-2` | uses OpenAI compat |
| Groq | `groq:` | `groq:llama-4-scout-17b-16e-instruct` | `[groq]` |
| Mistral | `mistral:` | `mistral:mistral-large-latest` | `[mistral]` |
| Cohere | `cohere:` | `cohere:command-r-plus` | `[cohere]` |

### Cloud Platforms

| Platform | Prefix | Example |
|---|---|---|
| Azure AI Foundry | `azure:` | `azure:gpt-5.2` |
| Amazon Bedrock | `bedrock:` | `bedrock:anthropic.claude-sonnet-4-6` |
| Google Vertex AI | `vertex:` | `vertex:gemini-3-flash-preview` |
| Heroku | `heroku:` | (via OpenAI compat) |

### Aggregators & Routers

| Service | Prefix | Example |
|---|---|---|
| OpenRouter | `openrouter:` | `openrouter:anthropic/claude-sonnet-4-6` |
| Together AI | `together:` | `together:meta-llama/Llama-4-405b` |
| Fireworks AI | `fireworks:` | `fireworks:accounts/.../models/...` |
| LiteLLM | via proxy | any model |

### Local Models

| Runtime | Prefix | Example |
|---|---|---|
| Ollama | `ollama:` | `ollama:llama3.2` |
| Outlines | `outlines:` | structured generation |

## Model Settings

### Common Settings (All Providers)

```python
from pydantic_ai import ModelSettings

ModelSettings(
    temperature=0.7,
    max_tokens=4096,
    timeout=30.0,       # seconds
    top_p=0.9,
)
```

### Provider-Specific Settings

```python
from pydantic_ai.models.google import GoogleModelSettings

GoogleModelSettings(
    temperature=0.0,
    gemini_safety_settings=[
        {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_LOW_AND_ABOVE'},
    ],
)
```

Each provider may have its own `ModelSettings` subclass with extra parameters.

### Settings Precedence (lowest to highest)

1. Model-level defaults (set when creating the model object)
2. Agent-level defaults (`Agent(model_settings=...)`)
3. Run-time overrides (`agent.run(model_settings=...)`)

Settings are merged — run-time values override agent-level, which override model-level.

## Runtime Model Override

Switch models per-run without changing the agent:

```python
agent = Agent('openai:gpt-5.2')

# Use a different model for this specific run
result = await agent.run('prompt', model='anthropic:claude-sonnet-4-6')
```

## Custom Models

Implement the `Model` interface to support any provider:

```python
from pydantic_ai.models import Model

class MyCustomModel(Model):
    async def request(self, messages, model_settings, model_request_parameters):
        # Call your custom LLM API
        ...
```

## OpenAI-Compatible APIs

Many providers expose OpenAI-compatible endpoints. Use the OpenAI provider with a custom base URL:

```python
from pydantic_ai.models.openai import OpenAIModel

model = OpenAIModel(
    'my-model-name',
    provider=OpenAIProvider(base_url='https://my-provider.com/v1', api_key='...'),
)
agent = Agent(model)
```

## Model Selection Guidelines

- **Best quality**: `openai:gpt-5.2`, `anthropic:claude-opus-4-6`
- **Good quality, fast**: `anthropic:claude-sonnet-4-6`, `google:gemini-3-flash-preview`
- **Cost-effective**: `openai:gpt-5-mini`, `deepseek:deepseek-chat`
- **Local/private**: `ollama:llama3.2`
- **Delegation pattern**: Use expensive models for orchestration, cheaper for subtasks
