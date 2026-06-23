from pathlib import Path

counter = Path("primary.count")
count = int(counter.read_text() if counter.exists() else "0") + 1
counter.write_text(str(count), encoding="utf-8")
print(f"primary attempt {count}")
raise SystemExit(1)
