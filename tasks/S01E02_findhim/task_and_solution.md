# S01E02 — Find Him

## Task

Determine which transport suspect (from S01E01) is nearest to an active nuclear power plant, retrieve their access level, and submit the answer to the hub API.

## Solution

An LLM-driven agent loop orchestrates 5 tools: load suspects (reuses S01E01 filtering + tagging), fetch power plants and geocode active ones via Nominatim, query hub API for each suspect's known locations, compute haversine distances between all suspect–plant pairs to find the closest match, and retrieve the suspect's access level from the hub.

## Reasoning

The task instructions suggest a function-calling approach — the LLM decides which tools to invoke and in what order, handling the multi-step workflow (load data → geocode → compute distances → query access). All computation (haversine, geocoding) is done in code, not delegated to the LLM, keeping results deterministic.
