#!/bin/bash
export TELEGRAM_BOT_TOKEN="8898227219:AAHd2KbeaZ_HUbt6H1EaPDmzBLW1dibby6E"
cd /root/cloud_brain
python3 brain.py 2>&1 | tee brain.log
