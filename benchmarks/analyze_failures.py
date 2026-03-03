import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
with open("d:\\PROG\\TEST\\SMART_HOME_V2\\benchmarks\\reports\\benchmark_v2_report_iteration7.json", encoding="utf-8") as f:
    data = json.load(f)

for r in data["results"]:
    if not r["score"]["success"]:
        print(f"[{r['id']}] {r['user_input']}")
        print(f"  Attendu: {r['expected']}")
        print(f"  Obtenu: {r['parsed_calls']}")
