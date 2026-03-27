# S03E02 — Firmware

## Task

A firmware binary (`cooler.bin`) on a restricted Linux VM fails to run correctly. Connect to the VM via a shell API, debug the firmware configuration, find the password, fix `settings.ini`, run the binary, and extract the ECCS confirmation code. Submit the code to the hub.

## Solution

Hybrid architecture — hardcoded init steps followed by an LLM-driven agent loop using native OpenAI SDK with GPT-5.4 via OpenRouter:

1. **Init phase** (hardcoded): Reboot VM, fetch `help` to discover available commands, list `/opt/firmware` and `/opt/firmware/cooler`, scan `.gitignore` to build a forbidden paths list.
2. **Agent loop** (OpenAI function calling, max 50 iterations): The LLM receives the init context in the system prompt and uses three tools:
   - `execute_shell_command` — runs commands via the shell API with safety checks (forbidden path blocking, binary file blocking, command validation, 2s throttle)
   - `sleep_seconds` — waits after bans (capped at 180s)
   - `submit_answer` — submits the ECCS code as `{"confirmation": code}`

The `ShellClient` class encapsulates all HTTP communication with retry logic (tenacity, 6 attempts with exponential backoff for 503/429), forbidden path enforcement (system paths + `.gitignore`-derived paths saved to `.workspace/forbidden_paths.csv`), and response truncation to prevent context blowup from binary files.

Langfuse tracing via `langfuse.openai.register_tracing()` for automatic LLM call observability.

## Reasoning

The hybrid architecture front-loads deterministic exploration (reboot, help, directory listing) to give the LLM maximum context from the start, reducing wasted iterations. The forbidden paths system (both static prefixes and dynamic `.gitignore` scanning) prevents bans that reset the VM. Binary file blocking avoids context corruption. The 2s API throttle prevents rate limiting. Using the native OpenAI SDK (not LangChain) gives direct access to function calling and token usage reporting with minimal abstraction overhead.
