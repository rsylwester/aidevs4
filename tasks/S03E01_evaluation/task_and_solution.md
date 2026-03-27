# S03E01 — Evaluation

## Task

Detect anomalies in 10,000 sensor JSON files. Each file contains sensor readings (temperature, humidity, PM2.5, PM10, pressure) and an operator note. Identify files with data anomalies or suspicious operator notes and submit the list of anomalous file IDs.

## Solution

Two-pass anomaly detection — programmatic checks first, then LLM classification:

1. **Download & extract**: Fetch `sensors.zip`, extract 10,000 JSON files to `.workspace/sensors/`.
2. **Programmatic checks**: Validate each sensor record against physical plausibility rules (temperature ranges, humidity 0-100%, PM thresholds, pressure bounds). Files failing any check are flagged as anomalies immediately.
3. **LLM note classification**: For files that pass data checks, deduplicate unique operator notes, then batch-classify them with an LLM to detect suspicious/anomalous notes (e.g., notes describing equipment failures, unusual observations). Flagged notes map back to their file IDs.
4. **Submit**: Merge both anomaly sets, sort IDs, submit as `{"recheck": sorted_ids}`.

## Reasoning

The two-pass approach minimizes LLM usage — programmatic checks handle the majority of anomalies (obvious out-of-range values) without any API calls. Deduplicating notes before LLM classification reduces the number of LLM calls from potentially thousands to the number of unique notes. This is both faster and cheaper than classifying every file individually.
