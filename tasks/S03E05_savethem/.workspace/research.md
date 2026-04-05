# S03E05 – Save Them: Research

## APIs Discovered

### Tool Search: `POST /api/toolsearch`
- Params: `apikey`, `query` (keywords or natural language)
- Returns top 3 matching tools with name, url, description, score

### Maps: `POST /api/maps`
- Params: `apikey`, `query` (city name)
- Returns 10x10 grid map for the city
- Query must be just the city name (e.g., "Skolwin")

### Vehicles (note: API spells it "wehicles"): `POST /api/wehicles`
- Params: `apikey`, `query` (vehicle name: rocket|horse|walk|car)
- Returns vehicle info and consumption rates

### Books: `POST /api/books`
- Params: `apikey`, `query` (search terms)
- Returns top 3 matching notes from archive

---

## Map: Skolwin (10x10)

```
........WW   row 0
.......WW.   row 1
.T....WW..   row 2
......W...   row 3
..T...W.G.   row 4  (G = goal at col 8)
....R.W...   row 5
...RR.WW..   row 6
SR.....W..   row 7  (S = start at col 0)
......WW..   row 8
.....WW...   row 9
```

### Legend
- `.` = open ground (passable)
- `T` = tree (passable, +0.2 fuel penalty for powered vehicles)
- `W` = water (only horse and walk can cross)
- `R` = rock (completely blocks movement)
- `S` = start (row 7, col 0)
- `G` = goal (row 4, col 8)

---

## Vehicles

| Vehicle | Fuel/move | Food/move | Notes |
|---------|-----------|-----------|-------|
| rocket  | 1.0       | 0.1       | Cannot cross water. Fastest but fuel-hungry. |
| car     | 0.7       | 1.0       | Cannot cross water. Balanced. |
| horse   | 0.0       | 1.6       | CAN cross water. No fuel needed. |
| walk    | 0.0       | 2.5       | CAN cross water. No fuel needed. Highest food cost. |

## Resources
- 10 fuel, 10 food at start

---

## Rules Summary

1. **Vehicle choice** is made at the start (first element of answer array). Cannot switch vehicles mid-route.
2. **Dismount** command: leave vehicle and continue on foot (walk mode). One-way — cannot remount.
3. **Resources consumed per move** (not at selection). Running out of either = mission failure.
4. **Tree penalty**: +0.2 extra fuel when entering a T tile with powered vehicle (rocket/car).
5. **No refueling** stations on the map.
6. **Water**: only horse and walk can cross. Car and rocket cannot.
7. **Rocks**: block all movement modes.

## Answer Format

```json
["vehicle_name", "direction", "direction", ...]
```
Directions: "up", "down", "left", "right"
Special: "dismount" (switch to walk mode mid-route)

## Key Observations

- The river (W tiles) runs diagonally through the middle of the map, separating S from G.
- Must cross the river to reach G.
- Rocket and car CANNOT cross water → must use horse, walk, or dismount before river.
- Horse: 0 fuel, 1.6 food/move. For a ~11-move path, that's 17.6 food (too much! only have 10).
- Walk: 0 fuel, 2.5 food/move. Even worse for food.
- Car + dismount: use car for non-water tiles, dismount before water, walk through water.
- Rocket + dismount: similar strategy but more fuel-hungry.

### Path Analysis

Start: (7, 0), Goal: (4, 8)
Need to go roughly: up 3, right 8 = minimum 11 moves

The river of W tiles runs roughly along column 6-7. Must find a crossing point.

Possible crossing points (gaps in W):
- Row 3: W only at col 6 → cols 7-9 are open on east side
- Row 7: W only at col 7 → can go through col 5-6 then cross at row 3 or 4

Looking at the map more carefully:
```
Col:  0 1 2 3 4 5 6 7 8 9
R0:   . . . . . . . . W W
R1:   . . . . . . . W W .
R2:   . T . . . . W W . .
R3:   . . . . . . W . . .
R4:   . . T . . . W . G .
R5:   . . . . R . W . . .
R6:   . . . R R . W W . .
R7:   S R . . . . . W . .
R8:   . . . . . . W W . .
R9:   . . . . . W W . . .
```

Need to cross the W barrier. Narrowest point is row 3 (single W at col 6) or row 7 (single W at col 7).
From row 7 going east: S(7,0) → blocked by R at (7,1). Must go up first or around.
