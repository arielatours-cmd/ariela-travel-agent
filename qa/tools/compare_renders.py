"""Compare two render JSONs (from render_pages.py / render_member_pages.py): print same/DIFF per page and the
changed snippets. Usage: python3 qa/tools/compare_renders.py before.json after.json"""
import json, sys, difflib
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
for k in a:
    if k not in b:
        print(k, "MISSING in after"); continue
    same = a[k][1] == b[k][1]
    print(k, a[k][0], b[k][0], "same" if same else "DIFF")
    if not same:
        sm = difflib.SequenceMatcher(None, a[k][1], b[k][1], autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "equal":
                print("   ", op, repr(a[k][1][max(0, i1-40):i2+40][:200]), "->", repr(b[k][1][max(0, j1-40):j2+40][:200]))
