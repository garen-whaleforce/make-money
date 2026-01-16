#!/bin/bash
# Deploy Daily Brief Pipeline to gpu5090 server
# Usage: ./scripts/deploy-server.sh

set -e

SERVER="service@172.23.22.100"
REMOTE_DIR="~/daily-brief"
LOCAL_DIR="$(dirname "$0")/.."

echo "=== Daily Brief Server Deployment ==="
echo "Server: $SERVER"
echo "Remote: $REMOTE_DIR"
echo ""

# Step 1: Check SSH connection
echo "[1/6] Checking SSH connection..."
ssh -o ConnectTimeout=5 $SERVER "echo 'SSH OK'" || { echo "SSH failed"; exit 1; }

# Step 2: Create remote directory
echo "[2/6] Creating remote directory..."
ssh $SERVER "mkdir -p $REMOTE_DIR/{out,data/artifacts,data/run_reports}"

# Step 3: Upload project files
echo "[3/6] Uploading project files..."
rsync -avz --progress \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'out/*' \
    --exclude 'data/artifacts/*' \
    --exclude 'data/run_reports/*' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude '.env.server' \
    --exclude 'node_modules' \
    "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

# Step 4: Check if .env.server exists
echo "[4/6] Checking environment file..."
ssh $SERVER "
    cd $REMOTE_DIR
    if [ ! -f .env.server ]; then
        echo '⚠️  .env.server not found!'
        echo 'Please create it from .env.server.example:'
        echo '  ssh $SERVER'
        echo '  cd $REMOTE_DIR'
        echo '  cp .env.server.example .env.server'
        echo '  nano .env.server'
        exit 1
    fi
    echo '✓ .env.server exists'
"

# Step 5: Build Docker image
echo "[5/6] Building Docker image..."
ssh $SERVER "
    cd $REMOTE_DIR
    docker compose -f docker-compose.server.yml build
"

# Step 6: Set up cron job
echo "[6/6] Setting up cron job..."
ssh $SERVER "
    cd $REMOTE_DIR

    # Create run script
    cat > run-daily-brief.sh << 'SCRIPT'
#!/bin/bash
cd ~/daily-brief
docker compose -f docker-compose.server.yml up --build 2>&1 | tee -a logs/\$(date +%Y%m%d).log
SCRIPT
    chmod +x run-daily-brief.sh
    mkdir -p logs

    # Add cron job (Taiwan 06:00 = UTC 22:00)
    CRON_JOB='0 22 * * * cd ~/daily-brief && ./run-daily-brief.sh >> logs/cron.log 2>&1'

    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q 'daily-brief'; then
        echo '✓ Cron job already exists'
        crontab -l | grep daily-brief
    else
        # Add new cron job
        (crontab -l 2>/dev/null; echo \"\$CRON_JOB\") | crontab -
        echo '✓ Cron job added:'
        crontab -l | grep daily-brief
    fi
"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Cron Schedule: 0 22 * * * (UTC) = Taiwan 06:00 daily"
echo ""
echo "Manual run:"
echo "  ssh $SERVER"
echo "  cd ~/daily-brief"
echo "  ./run-daily-brief.sh"
echo ""
echo "View logs:"
echo "  ssh $SERVER 'tail -f ~/daily-brief/logs/cron.log'"
