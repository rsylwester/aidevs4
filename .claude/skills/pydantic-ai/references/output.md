# Structured Output — Deep Reference

## Output Type Options

### Scalar Types

```python
agent = Agent('model', output_type=int)
agent = Agent('model', output_type=str)  # default
agent = Agent('model', output_type=float)
agent = Agent('model', output_type=bool)
```

### Pydantic Models

```python
class CityLocation(BaseModel):
    city: str
    country: str = Field(description='ISO country code')

agent = Agent('model', output_type=CityLocation)
result = agent.run_sync('Where were the 2012 Olympics?')
print(result.output.city)  # 'London'
```

### Dataclasses and TypedDict

```python
@dataclass
class Point:
    x: float
    y: float

agent = Agent('model', output_type=Point)
```

### Multiple Output Types (List Syntax)

Preferred over union syntax for type checking:

```python
class Success(BaseModel):
    data: str

class Error(BaseModel):
    message: str

agent = Agent('model', output_type=[Success, Error])
# Each type becomes a separate tool the LLM can call
```

### Union Syntax

Requires explicit generic parameters and `# type: ignore`:

```python
agent = Agent[None, Success | Error](
    'model',
    output_type=Success | Error,  # type: ignore
)
```

## Output Modes

### ToolOutput (Default)

Uses LLM tool calls. Works with virtually all models:

```python
from pydantic_ai import ToolOutput

agent = Agent(
    'model',
    output_type=[
        ToolOutput(Fruit, name='return_fruit', description='Return a fruit'),
        ToolOutput(Vehicle, name='return_vehicle'),
    ],
)
```

### NativeOutput

Uses the model's built-in structured output feature (not all models support this):

```python
from pydantic_ai import NativeOutput

agent = Agent(
    'openai:gpt-5.2',
    output_type=NativeOutput(
        [Fruit, Vehicle],
        name='fruit_or_vehicle',
        description='Return either a fruit or vehicle.',
    ),
)
```

Caveat: Gemini cannot use tools simultaneously with native structured output.

### PromptedOutput

Injects JSON schema into the prompt; model outputs JSON text:

```python
from pydantic_ai import PromptedOutput

agent = Agent(
    'model',
    output_type=PromptedOutput(
        [Vehicle, Device],
        name='vehicle_or_device',
        template='Respond with JSON matching this schema: {schema}',
    ),
)
```

## Output Functions

Functions the LLM can call that produce the agent's output. Enables post-processing:

```python
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry

class Row(BaseModel):
    name: str
    country: str

def run_sql_query(query: str) -> list[Row]:
    """Execute an SQL query against the database."""
    if not query.upper().startswith('SELECT'):
        raise ModelRetry('Only SELECT queries are allowed.')
    return db.execute(query)

agent = Agent[None, list[Row] | str](
    'model',
    output_type=[run_sql_query, str],  # type: ignore
    instructions='You are a SQL agent.',
)
```

Output functions can take `RunContext` as first parameter:

```python
async def hand_off(ctx: RunContext[MyDeps], query: str) -> list[Row]:
    """Delegate to specialist agent."""
    result = await specialist.run(query, message_history=ctx.messages[:-1])
    return result.output
```

## TextOutput

Process the LLM's plain text response through a function:

```python
from pydantic_ai import TextOutput

def parse_csv(text: str) -> list[list[str]]:
    return [line.split(',') for line in text.strip().split('\n')]

agent = Agent('model', output_type=TextOutput(parse_csv))
```

Can combine with ToolOutput in a list:
```python
agent = Agent('model', output_type=[TextOutput(parse_csv), ToolOutput(StructuredData)])
```

## StructuredDict (Custom JSON Schema)

For dynamic or externally-defined schemas:

```python
from pydantic_ai import StructuredDict

schema = StructuredDict(
    {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
    name='Person',
    description='A person record',
)
agent = Agent('model', output_type=schema)
result = agent.run_sync('Create a person')  # Returns dict[str, Any]
```

Note: no Pydantic validation is performed on the result — only JSON schema guidance to the LLM.

## Output Validators

Async validation with access to dependencies:

```python
@agent.output_validator
async def validate_output(ctx: RunContext[MyDeps], output: MyOutput) -> MyOutput:
    if not await ctx.deps.db.verify(output.id):
        raise ModelRetry(f'ID {output.id} not found in database. Pick a valid one.')
    return output
```

- Raise `ModelRetry` to ask the LLM to try again with feedback
- Can modify and return the output (e.g., enrich with computed fields)
- Runs after Pydantic validation but before returning to caller

## Validation Context

Pass context to Pydantic field validators:

```python
from pydantic import BaseModel, field_validator, ValidationInfo

class Value(BaseModel):
    x: int

    @field_validator('x')
    def check(cls, v: int, info: ValidationInfo) -> int:
        return v + (info.context or 0)

# Static context
agent = Agent('model', output_type=Value, validation_context=10)

# Dynamic from deps
agent = Agent('model', output_type=Value, deps_type=MyDeps,
              validation_context=lambda ctx: ctx.deps.offset)
```

## Streaming Output

```python
async with agent.run_stream('prompt') as response:
    async for partial in response.stream_output():
        # Each `partial` is a partially-validated OutputType
        print(partial)
```

For output functions with side effects, check `ctx.partial_output`:

```python
def save(ctx: RunContext, record: Record) -> Record:
    if ctx.partial_output:
        return record  # Don't save partial data
    db.save(record)
    return record
```

## Image Output

```python
from pydantic_ai import BinaryImage

agent = Agent('openai-responses:gpt-5.2', output_type=BinaryImage)
result = agent.run_sync('Generate an image of a cat.')
# result.output is binary image data
```
