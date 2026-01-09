from app import app

print("\n=== All Registered Routes ===")
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    methods = ', '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
    print(f"{rule.rule:50s} [{methods}]")

print("\n=== Audio/Gemini Related Routes ===")
for rule in app.url_map.iter_rules():
    if 'audio' in rule.rule.lower() or 'gemini' in rule.rule.lower():
        methods = ', '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        print(f"{rule.rule:50s} [{methods}] - {rule.endpoint}")
