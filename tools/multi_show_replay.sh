#!/bin/bash
set -e
shows=("Nova" "Super Nova" "Northern Lights" "Tidal Wave" "Desert Skies" "Peruvian Paradise")
for show in "${shows[@]}"; do
    safe="${show// /_}"
    echo "================================================================"
    echo ">>> Replay-testing: $show"
    echo "================================================================"
    COLORSPLASH_API_KEY="$(cat /tmp/colorsplash-key)" \
      .venv/bin/python tools/replay_probe.py \
        --show "$show" --count 3 \
        --observe-secs 35 --reset-secs 20 --ambient-sample 2 \
        --roi-cx 675 --roi-cy 185 --roi-half 60 \
        --output "tools/show_colors_replay_${safe}.json" \
        --events-log "tools/replay_events_${safe}.jsonl"
done
echo ""
echo ">>> All 6 shows complete."
