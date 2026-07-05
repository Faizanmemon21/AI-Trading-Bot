"""
Run this ONCE in your crypto-trading-bot folder:
  python fix_dashboard_capital.py

It finds the $10,000 capital display in dashboard.py
and changes it to $100 to match your test budget.
"""
import re

with open("dashboard.py", "r") as f:
    content = f.read()

# Find and replace capital amount - handles various formats
patterns = [
    (r'\$10,000', '$100'),
    (r'\$10000', '$100'),
    (r'10,000\.00', '100.00'),
    (r'"10000"', '"100"'),
    (r"'10000'", "'100'"),
    (r'10000\.0', '100.0'),
    (r'TESTNET_BUDGET.*?10000', lambda m: m.group(0).replace('10000','100')),
]

changes = 0
for pattern, replacement in patterns:
    if callable(replacement):
        new_content, n = re.subn(pattern, replacement, content)
    else:
        new_content = content.replace(
            pattern.replace(r'\$','$').replace(r'\.','.')
                   .replace(r'\b',''), 
            replacement
        )
        n = content.count(pattern.replace(r'\$','$').replace(r'\.','.')
                                 .replace(r'\b',''))
    if n > 0:
        content = new_content
        changes += n
        print(f"  ✅ Replaced '{pattern}' → '{replacement}' ({n}x)")

if changes == 0:
    print("  ⚠️  No hardcoded $10,000 found in dashboard.py")
    print("  The capital might come from bot_state.json stats")
    print()
    print("  Try this instead — open dashboard.py and search for:")
    print("  '10000' or '$10,000' or 'BUDGET' or 'capital'")
else:
    with open("dashboard.py", "w") as f:
        f.write(content)
    print(f"\n✅ Done! Changed {changes} values. Restart dashboard.py to see $100.")
