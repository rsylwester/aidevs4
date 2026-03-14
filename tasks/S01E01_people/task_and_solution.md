# S01E01 — People

## Task

Find male transport workers from Grudziadz born between 1986–2006. Download a CSV of people, filter by demographics, classify their jobs, and submit matching candidates to the hub API.

## Solution

Filter `people.csv` by gender (M), birth city (Grudziadz), and birth year range (1986–2006). Send all filtered candidates' job descriptions to the LLM in a single batch call using `.with_structured_output()` to tag each job into categories (transport, IT, medycyna, etc.). Keep only people tagged "transport" and submit them.

## Reasoning

Structured output eliminates fragile regex/string parsing of LLM responses — the model returns typed `PersonTags` objects directly. Batching all jobs in one LLM call reduces API round-trips compared to per-person classification. Demographic filtering happens in code before the LLM call, keeping the expensive step minimal.
