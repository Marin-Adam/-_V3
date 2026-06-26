#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# V3.0 启动脚本 — AI-Native 电商实时监控智能决策平台
# ═══════════════════════════════════════════════════════════════════════
#
# Usage:
#   bash start.sh              # 启动全部服务
#   bash start.sh backend      # 仅启动后端
#   bash start.sh frontend     # 仅启动前端
#   bash start.sh micro        # 启动 A2A 微服务
#   bash start.sh stop         # 停止全部服务
#   bash start.sh status       # 查看服务状态
#
# Requirements:
#   - Python 3.12+
#   - Node.js 18+
#   - Docker Compose (for PostgreSQL/Redis/Milvus)
# ═══════════════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
MICRO_DIR="$PROJECT_DIR/microservices"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERR]${NC} $1"; }

# ── Infrastructure ────────────────────────────────────────────────────
start_infra() {
    log_info "Starting Docker infrastructure (PostgreSQL + Redis + Milvus)..."
    cd "$PROJECT_DIR"
    docker compose up -d postgres redis 2>/dev/null || docker-compose up -d postgres redis
    sleep 2
    log_ok "Infrastructure started (PostgreSQL:5432, Redis:6379)"
}

# ── Backend ───────────────────────────────────────────────────────────
start_backend() {
    log_info "Starting FastAPI backend on port 8001..."
    cd "$BACKEND_DIR"

    # Create .env if not exists
    if [ ! -f .env ]; then
        log_warn "Creating default .env file..."
        cat > .env << 'EOF'
DEBUG=true
APP_NAME="ECom AI Dashboard"
APP_VERSION="3.0.0"
DATABASE_URL=postgresql+asyncpg://ecom:ecom2024@localhost:5432/ecom_dashboard
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-key-change-in-production
DATA_SOURCE=auto
MCP_SERVER_ENABLED=true
A2A_ENABLED=true
EOF
        log_ok ".env created"
    fi

    # Install dependencies if needed
    if [ ! -d "__pycache__" ] && [ ! -f ".deps_installed" ]; then
        log_info "Installing Python dependencies..."
        pip install -r requirements.txt -q
        touch .deps_installed
    fi

    log_info "Starting uvicorn..."
    uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload &
    BACKEND_PID=$!
    echo $BACKEND_PID > /tmp/ecom_backend.pid
    sleep 2
    if kill -0 $BACKEND_PID 2>/dev/null; then
        log_ok "Backend started (PID: $BACKEND_PID, port: 8001)"
        log_info "API docs: http://localhost:8001/docs"
    else
        log_err "Backend failed to start"
    fi
}

# ── Frontend ──────────────────────────────────────────────────────────
start_frontend() {
    log_info "Starting Vue 3 frontend on port 5173..."
    cd "$FRONTEND_DIR"

    if [ ! -d "node_modules" ]; then
        log_info "Installing npm dependencies..."
        npm install
    fi

    npm run dev &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > /tmp/ecom_frontend.pid
    sleep 2
    log_ok "Frontend started (PID: $FRONTEND_PID, port: 5173)"
    log_info "Open: http://localhost:5173"
}

# ── Microservices (A2A Agents) ────────────────────────────────────────
start_microservices() {
    log_info "Starting A2A Agent microservices..."
    cd "$BACKEND_DIR"

    # Start each agent in background
    uvicorn microservices.data_agent.main:app --host 0.0.0.0 --port 8010 &
    echo $! > /tmp/ecom_data_agent.pid
    log_ok "DataAgent started on :8010"

    uvicorn microservices.analyze_agent.main:app --host 0.0.0.0 --port 8011 &
    echo $! > /tmp/ecom_analyze_agent.pid
    log_ok "AnalyzeAgent started on :8011"

    uvicorn microservices.sentiment_agent.main:app --host 0.0.0.0 --port 8012 &
    echo $! > /tmp/ecom_sentiment_agent.pid
    log_ok "SentimentAgent started on :8012"

    uvicorn microservices.report_agent.main:app --host 0.0.0.0 --port 8013 &
    echo $! > /tmp/ecom_report_agent.pid
    log_ok "ReportAgent started on :8013"
}

# ── Stop ──────────────────────────────────────────────────────────────
stop_all() {
    log_info "Stopping all services..."
    for pidfile in /tmp/ecom_backend.pid /tmp/ecom_frontend.pid /tmp/ecom_data_agent.pid /tmp/ecom_analyze_agent.pid /tmp/ecom_sentiment_agent.pid /tmp/ecom_report_agent.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                log_ok "Stopped PID $pid ($(basename $pidfile))"
            fi
            rm -f "$pidfile"
        fi
    done
    log_ok "All services stopped"
}

# ── Status ────────────────────────────────────────────────────────────
show_status() {
    echo "=== Service Status ==="
    curl -s http://localhost:8001/health 2>/dev/null && echo "" || echo "Backend: ❌ (port 8001)"
    curl -s http://localhost:5173 2>/dev/null >/dev/null && echo "Frontend: ✅ (port 5173)" || echo "Frontend: ❌ (port 5173)"
    for port in 8010 8011 8012 8013; do
        curl -s http://localhost:$port/health 2>/dev/null | head -1 && echo "" || echo "Agent :$port: ❌"
    done
}

# ── Main ──────────────────────────────────────────────────────────────
case "${1:-all}" in
    backend)
        start_infra
        start_backend
        ;;
    frontend)
        start_frontend
        ;;
    micro)
        start_microservices
        ;;
    stop)
        stop_all
        ;;
    status)
        show_status
        ;;
    all)
        start_infra
        start_backend
        start_frontend
        log_info ""
        log_info "════════════════════════════════════════════════════════"
        log_ok  "V3.0 全部服务已启动!"
        log_info "  🖥️  Frontend : http://localhost:5173"
        log_info "  🔧  Backend  : http://localhost:8001"
        log_info "  📚  API Docs : http://localhost:8001/docs"
        log_info "  📊  Insights : http://localhost:5173/insights"
        log_info ""
        log_info "  启动微服务 (可选): bash start.sh micro"
        log_info "  停止全部:          bash start.sh stop"
        log_info "════════════════════════════════════════════════════════"
        ;;
    *)
        echo "Usage: bash start.sh [backend|frontend|micro|stop|status|all]"
        ;;
esac
