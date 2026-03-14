class Location:
    latitude: float
    longitude: float
    address: str
    raw: dict[str, object]

class Nominatim:
    def __init__(self, *, user_agent: str) -> None: ...
    def geocode(self, query: str) -> Location | None: ...
