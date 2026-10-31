# FinSight

Bank statement analyser for the hackathon's Problem 9. Full project context, decisions, results and backlog:

@HANDOFF.md

Working rules for this repo:
- Keep the core deterministic: no LLM in classification scoring or arithmetic; money in integer paise.
- Bump `RULES_VERSION` in `backend/app/config.py` whenever rules, weights or categories change.
- Run `python backend/tests/test_brief_examples.py`, `test_review_flow.py`, `test_tokens.py` and `smoke.py` before committing.
- Tune on the `datasets/multilingual_v1` dev split only; report on test.
- Flags say "review recommended", never "fraud".
