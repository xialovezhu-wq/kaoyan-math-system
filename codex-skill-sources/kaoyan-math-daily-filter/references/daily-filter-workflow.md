# Post-study Formal-card Filter

## 1. Freeze Scope

Record the completed section or date, the explicit formal-ID anchor set, and the current-set exclusion set. If the user is beginning today's study rather than reviewing a completed set, route to `kaoyan-math-warmup` and stop.

## 2. Retrieve Once

Run one command for all anchors:

```bash
python3 /path/to/kaoyan-math-daily-filter//Users/your-user/Documents/kaoyan-math/错题知识网络/scripts/intake_recommend.py \
  --date YYYY-MM-DD --seed-id GS-902 --seed-id LA-910 --top 5
```

Do not run one recommendation per seed.

## 3. Verify Ranking-critical Facts

For every final seed and candidate, compare the current formal card with the generated snapshot. Verify ID, status, source, knowledge, wrong point, method gap, evidence origin, latest actual learning date, all learning dates, and attempt count.

Count initial intake, wrong/redo history, mastery scoring, and actual delivery as activity. Do not count relation edits, Wiki edits, rebuild time, or file modification time alone. A proxy answer updates the anchor schedule, while activity age belongs to the formal card that was actually delivered. The bundled wrapper corrects this attribution and reads dated formal-card history without rewriting the repository script.

The auditable event set is formal `date`, `wrong_history`, `mastery_history`, rollback first/recurrence dates, delivered review events, warmup delivery, and any explicit current-task substantive update evidence. The repository has no complete history for undated metadata updates; state this limit and never substitute file mtime, relation maintenance, or Wiki maintenance as learning activity.

## 4. Filter And Rank

Exclude anchors, mastered cards, and cards with actual activity from day 0 through day 7. Rank exact concrete gap evidence first. Only after that layer is exhausted may a literal shared formal knowledge label provide a `knowledge_fallback`.

Existing `related` declarations and automated similarity are candidate signals only. Query `wrongnet.py related ID --ignore-declared` when independent relationship evidence matters.

## 5. Report And Stop

Stop at five or fewer. Include evidence provenance and required date metadata. State when the list is short because the formal library lacks eligible evidence. Never generate a replacement question.
