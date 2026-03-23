Scope note: This API controls a fictional in‑game drone. The guidance below is about constructing valid API instructions, not real-world operations.

1) Exact instruction string format expected in answer.instructions
- answer.instructions is an array of strings. Each element is a single command string.
- Zero-parameter commands are just the bare name with no parentheses:
  - selfCheck
  - getConfig
  - getFirmwareVersion
  - calibrateCompass
  - calibrateGPS
  - hardReset
  - flyToLocation
- Parameterized commands use parentheses, no quotes around parameters, no trailing semicolons:
  - setDestinationObject(ID)
    - ID must match [A-Z]{3}[0-9]+[A-Z]{2}, all uppercase letters. Example: setDestinationObject(BLD1234PL)
  - set(x,y)
    - x and y are positive integers, 1-based grid coordinates, no spaces around the comma. Example: set(3,4)
  - set(Am)
    - Flight altitude in meters, 1–100 inclusive, with a mandatory “m” suffix, no space. Example: set(20m)
  - set(P%)
    - Engine power 0–100 inclusive, with a mandatory “%” suffix, no space. Example: set(75%)
  - set(engineON) or set(engineOFF)
    - Exactly these tokens; casing matters.
  - Mission objectives:
    - set(video), set(image), set(destroy), set(return)
  - setName(Name With Spaces)
    - Alphanumeric plus spaces only; do not quote the value. Example: setName(Fox 21)
  - setOwner(Firstname Lastname)
    - Exactly two words separated by a single space. Example: setOwner(Adam Kowalski)
  - setLed(#RRGGBB)
    - Hex color with leading #. Example: setLed(#00FFAA)
- Ordering constraints:
  - flyToLocation requires that altitude (set(Am)), destination object (setDestinationObject(...)), and landing sector (set(x,y)) are already set.
  - Mission objectives (set(destroy)/set(image)/set(video)/set(return)) can be queued in any order, but set them before flyToLocation to avoid starting a flight without objectives.

2) Functions/instructions actually needed for a bombing (destroy) mission
Required:
- setDestinationObject(...)
- set(x,y)  [landing sector on the destination’s map]
- set(Am)   [altitude 1–100m]
- set(destroy)
- flyToLocation
Optional (not required by the spec for execution but sometimes desirable):
- set(return)  [to ensure an automatic RTB with report]
- selfCheck  [diagnostic only]
- set(engineON), set(P%)  [engine/power; NOT listed as a prerequisite for flyToLocation]
Not needed/misleading for mission execution:
- setName, setOwner, setLed, calibrateCompass, calibrateGPS, hardReset, getConfig, getFirmwareVersion

3) Traps and misleading elements
- Overloaded set(...): The API disambiguates by parameter shape. You must supply exactly the right literal format:
  - Altitude must include “m” (e.g., set(20m)), not set(20) or set(20 m).
  - Power must include “%” (e.g., set(75%)), not set(75).
  - Engine control must be set(engineON)/set(engineOFF) exactly; set(on) or set(start) will fail.
- flyToLocation takes no parentheses. Use flyToLocation, not flyToLocation().
- Zero-parameter commands never use parentheses (e.g., selfCheck, not selfCheck()).
- Landing sector is 1-based (1,1 is the top-left). Using 0,0 is invalid.
- set(x,y) applies “on the map of the object,” so it should follow setDestinationObject(...) to avoid missing context.
- Destination IDs must be uppercase letters/numbers per [A-Z]{3}[0-9]+[A-Z]{2}; mixed/lowercase will fail.
- answer.instructions must be an array of plain strings; do not send objects like {"cmd":"set",...}.
- Engine and power settings are listed but not prerequisites for flight; don’t assume you must call set(engineON) or set(100%).
- “set(xm)” in the table is a schematic; xm is not a literal. Pass a number with “m” suffix (e.g., set(50m)).

4) Minimal correct sequence (exact strings) to set destination, set landing sector, configure flight, set mission objective to destroy, and initiate flight
- setDestinationObject(BLD1234PL)
- set(3,4)
- set(20m)
- set(destroy)
- flyToLocation

Notes:
- Replace BLD1234PL with a valid target ID matching the regex.
- Replace 3,4 with valid sector coordinates for that object.
- Replace 20m with your desired altitude (1–100m).
- If you also want an automatic return, insert set(return) anywhere before flyToLocation.