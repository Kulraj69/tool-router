"""Reproduces the demo video's real output: schema-validated tool calls."""
from tool_router import ToolRouter

r = ToolRouter()
r.register("search", {"type":"object","properties":{"q":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["q"]},
           lambda q, limit=5: {"hits":[f"result {i+1} for '{q}'" for i in range(min(limit,3))]}, "Web search")  # fixture
r.register("calendar.today", {"type":"object","properties":{}}, lambda: {"date":"2026-11-09"}, "Today's date")  # fixture
r.register("flights.book", {"type":"object","properties":{"offer_id":{"type":"string"},"passengers":{"type":"integer","minimum":1}},"required":["offer_id","passengers"]},
           lambda offer_id, passengers: {"pnr":"X7K2PQ","offer":offer_id,"passengers":passengers}, "Book a flight offer")  # fixture

CALLS = [
  '{"tool":"search","args":{"q":"cheapest BLR-DEL flight tomorrow","limit":3}}',
  '{"tool":"calendar.today","args":{}}',
  '{"tool":"search","args":{"limit":3}}',
  '{"tool":"flights.book","args":{"offer_id":"IX-0610","passengers":0}}',
  '{"tool":"shell.exec","args":{"cmd":"rm -rf /"}}',
]
if __name__ == "__main__":
    for raw in CALLS:
        print("call:", raw)
        v = r.parse_and_execute(raw)
        print("  ->", v)
