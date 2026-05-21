#!/bin/bash

# 1. Sync the files from your Mac to the Ubuntu server
echo "🚀 Pushing code to cloud server..."
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.git' ~/tradeVu/ ubuntu@80.225.252.185:~/tradeVu/ -e "ssh -i ~/Documents/ssh-key-2026-05-20.key"

# 2. Restart the docker container on the server to pick up the new Python files
echo "🔄 Restarting bot on server..."
ssh -i ~/Documents/ssh-key-2026-05-20.key ubuntu@80.225.252.185 "cd ~/tradeVu && sudo docker-compose restart"

echo "✅ Done! Your cloud dashboard is fully updated."
