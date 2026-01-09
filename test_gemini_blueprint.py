#!/usr/bin/env python
"""Test blueprint registration for Gemini TTS"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.getcwd())

print("=" * 60)
print("Blueprint Registration Test")
print("=" * 60)

# Test 1: Can we import the module?
print("\n1. Testing module import...")
try:
    from routes.v1.audio import google_tts
    print("   ✓ Module imported successfully")
except Exception as e:
    print(f"   ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Does the blueprint exist?
print("\n2. Checking blueprint object...")
if hasattr(google_tts, 'blueprint'):
    bp = google_tts.blueprint
    print(f"   ✓ Blueprint found: {bp.name}")
else:
    print("   ✗ No 'blueprint' attribute found")
    sys.exit(1)

# Test 3: What routes are registered?
print("\n3. Registered routes on blueprint:")
try:
    # blueprints store their routes differently before being registered
    if hasattr(bp, 'deferred_functions'):
        print(f"   Found {len(bp.deferred_functions)} deferred functions")
        for func in bp.deferred_functions:
            print(f"   - {func}")
except Exception as e:
    print(f"   Could not list deferred functions: {e}")

# Test 4: Register with Flask and check
print("\n4. Testing Flask registration...")
try:
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(bp)
    
    print(f"   ✓ Blueprint registered to Flask app")
    print("\n   Routes in Flask app:")
    for rule in app.url_map.iter_rules():
        if 'gemini' in rule.rule or 'audio' in rule.rule:
            methods = ', '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            print(f"   - {rule.rule:45s} [{methods}]")
    
except Exception as e:
    print(f"   ✗ Registration failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Auto-discovery test
print("\n5. Testing auto-discovery...")
try:
    from app_utils import discover_and_register_blueprints
    app2 = Flask(__name__)
    blueprints = discover_and_register_blueprints(app2, 'routes')
    
    print(f"   ✓ Discovered {len(blueprints)} blueprints total")
    print("\n   Audio/Gemini routes found:")
    found_gemini = False
    for rule in app2.url_map.iter_rules():
        if 'gemini' in rule.rule or 'audio' in rule.rule:
            methods = ', '.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            print(f"   - {rule.rule:45s} [{methods}]")
            if 'gemini' in rule.rule:
                found_gemini = True
    
    if found_gemini:
        print("\n   ✓ Gemini TTS route found via auto-discovery!")
    else:
        print("\n   ✗ Gemini TTS route NOT found via auto-discovery")
        print("\n   All discovered blueprints:")
        for bp in blueprints:
            print(f"   - {bp.name}")
        
except Exception as e:
    print(f"   ✗ Auto-discovery failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test Complete")
print("=" * 60)
