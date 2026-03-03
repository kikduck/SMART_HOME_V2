import sys, json
sys.stdout.reconfigure(encoding="utf-8")

reports = [
    ("A1", "SMART_HOME_V2/benchmarks/reports/bench_A1_r3.json"),
    ("A2", "SMART_HOME_V2/benchmarks/reports/bench_A2_r3.json"),
    ("B1", "SMART_HOME_V2/benchmarks/reports/bench_B1_r3.json"),
    ("B2", "SMART_HOME_V2/benchmarks/reports/bench_B2_r3.json"),
]

for name, path in reports:
    data = json.load(open(path, encoding="utf-8"))
    results = data["results"]
    total = len(results)
    passed = sum(1 for r in results if r["score"]["success"])
    fails = [r for r in results if not r["score"]["success"]]
    print(f"=== {name} : {passed}/{total} ===")
    for r in fails:
        print(f"  [{r['id']}] {r['user_input']}")
        print(f"    Attendu : {r['expected']}")
        print(f"    Obtenu  : {r['parsed_calls']}")
    print()
