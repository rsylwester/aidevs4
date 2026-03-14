# Tools — Deep Reference

## Registration Methods

### 1. Decorator-Based

```python
# With RunContext (access to deps, usage, retry count)
@agent.tool
async def get_balance(ctx: RunContext[MyDeps], account_id: int) -> float:
    """Get account balance.

    Args:
        account_id: The customer account ID.
    """
    return await ctx.deps.db.get_balance(account_id)

# Without RunContext
@agent.tool_plain
def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))  # simplified
```

### 2. Constructor Argument

```python
from pydantic_ai import Agent, Tool

agent = Agent(
    'openai:gpt-5.2',
    tools=[
        calculate,                          # Auto-detected as plain
        Tool(get_balance, takes_ctx=True),  # Explicit context flag
    ],
)
```

### 3. `Tool` Class Options

```python
Tool(
    function=my_func,
    takes_ctx=True,           # Whether first param is RunContext
    retries=5,                # Override agent default
    name='custom_name',       # Override function name
    description='...',        # Override docstring
    docstring_format='google',  # 'google' | 'numpy' | 'sphinx'
    require_parameter_descriptions=True,  # Error if params undocumented
)
```

## Docstring Extraction

Pydantic AI extracts tool descriptions and parameter schemas from docstrings:

```python
@agent.tool_plain(docstring_format='google')
def search(query: str, max_results: int = 10) -> list[str]:
    """Search the knowledge base.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return.
    """
```

Supported formats: Google (default), NumPy, Sphinx. First line becomes the tool description;
parameter descriptions populate the JSON schema sent to the LLM.

## RunContext

The `RunContext[DepsType]` dataclass is automatically injected as the first parameter of `@agent.tool` functions:

```python
@agent.tool
async def my_tool(ctx: RunContext[MyDeps], param: str) -> str:
    ctx.deps          # MyDeps instance
    ctx.usage         # RunUsage — token/request counts so far
    ctx.retry         # int — current retry attempt (0-based)
    ctx.messages      # list[ModelMessage] — conversation history
    ctx.run_step      # int — current run step
    ctx.partial_output  # bool — True during streaming partial outputs
    return 'result'
```

## Tool Return Types

Tools can return anything Pydantic can serialize to JSON: str, int, float, bool, dict, list,
dataclass, BaseModel, etc. For multi-modal output (images, etc.), see Advanced Tool Features
in the pydantic-ai docs.

## Retries and Error Handling

### ModelRetry

Signal to the LLM that its tool call was wrong and it should try again:

```python
from pydantic_ai import ModelRetry

@agent.tool_plain(retries=3)
def validate_code(code: str) -> str:
    """Validate Python code syntax."""
    try:
        compile(code, '<string>', 'exec')
        return 'Valid Python code.'
    except SyntaxError as e:
        raise ModelRetry(f'Syntax error at line {e.lineno}: {e.msg}. Fix and retry.')
```

The error message is sent back to the LLM, which generates a corrected tool call.

### Automatic Validation Retries

When tool arguments fail Pydantic validation (wrong types, missing fields), the validation error
is automatically sent to the LLM for retry — up to the configured retry limit.

## Prepare Functions

Dynamically modify tool availability and schema before each LLM request:

```python
from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

async def only_if_admin(
    ctx: RunContext[MyDeps], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Only show this tool to admin users."""
    if ctx.deps.user_role != 'admin':
        return None  # Hide the tool
    return tool_def  # Show unmodified

@agent.tool(prepare=only_if_admin)
async def delete_record(ctx: RunContext[MyDeps], record_id: int) -> str:
    """Delete a database record."""
    await ctx.deps.db.delete(record_id)
    return f'Deleted record {record_id}.'
```

Return `None` to hide the tool, or modify `tool_def` to change name/description/schema dynamically.

## Deferred Tools (Human-in-the-Loop)

Tools that require external approval before execution:

```python
@agent.tool(deferred=True)
async def transfer_funds(ctx: RunContext[BankDeps], amount: float, to: str) -> str:
    """Transfer money to another account."""
    await ctx.deps.bank.transfer(amount, to)
    return f'Transferred ${amount} to {to}.'
```

When `deferred=True`, the tool call is paused and exposed for approval (via the agent iteration API
or a UI). The calling code decides whether to approve, reject, or modify the call.

## Toolsets

Group tools into reusable collections. MCP servers are toolsets. You can also create custom ones:

```python
agent = Agent(
    'openai:gpt-5.2',
    tools=[individual_tool],
    toolsets=[mcp_server, another_toolset],
)
```
