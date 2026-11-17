#!/bin/bash
# Resume all experiments where they stopped (finished runs are skipped automatically).
# Keep the terminal / WSL session open while it runs (closing it stops WSL).
cd ~/leocc-g/project
sudo pkill -x iperf3; sudo pkill -x mm-delay
REPS=5 scripts/run_all.sh clk_q3300 -q 3300 2>&1 | tee -a results/clk_q3300.log
scripts/run_extra.sh clk_q3300 3300 2>&1 | tee -a results/clk_extra.log
