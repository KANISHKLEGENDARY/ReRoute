AGENT RULES (follow strictly, on every task)
1. Keep it as simple as possible. Do the smallest thing that works.
2. Reuse existing code. Add a new file only if truly needed, and say why in one line.
3. No new frameworks, layers, base classes or settings systems that I did not name.
4. Plain functions, short files (under 150 lines each), clear names, comments that explain WHY.
5. No extra features. If you think of one, write it under "Future work" in the README instead of building it.
6. Do not change the pipeline, policy engine or eval logic unless the task needs it.
7. Never put secrets in code or git. Verify library docs before using an API. Pin versions.
8. At the end, give a "Where to look" list: every new or changed file with one sentence in simple words, so I can learn it for interviews.
9. Report briefly: files changed, the commands to run, test counts. No long explanations.