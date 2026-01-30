#!/bin/bash
# quick status check for the osrm crawler running on the pi
ssh -o ConnectTimeout=5 raspberrypi.local \
  "ps aux | grep osrm-crawler | grep python | grep -v grep > /dev/null && echo 'RUNNING' || echo 'STOPPED'" \
  2>/dev/null || echo "PI UNREACHABLE"
echo "---"
ssh -o ConnectTimeout=5 raspberrypi.local \
  "tail -3 ~/jetspan/raw/osrm-crawler.log && echo '---' && cd ~/jetspan && ~/jetspan/venv/bin/python scripts/osrm-crawler.py --status" \
  2>/dev/null
