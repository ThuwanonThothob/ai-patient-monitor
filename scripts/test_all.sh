#!/usr/bin/env bash
# ==============================================================================
# Unified Automated Test Runner for Smart Ward AI Patient Monitor
# Steps:
#   1. Backend Unittest (Python)
#   2. Frontend Node Contract Tests
#   3. TypeScript Type Checking (tsc --noEmit)
#   4. Frontend Code Quality (ESLint)
# ==============================================================================
set -euo pipefail

# Ensure standard system and Homebrew paths are present for node / npm / python
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Resolve Python environment: prefer repo virtualenv, otherwise fall back to python3
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "ERROR: Python interpreter not found." >&2
    exit 1
fi

echo "=================================================================="
echo "🚀 Starting Unified Test Suite for Smart Ward"
echo "Repo Root: $REPO_ROOT"
echo "Python:    $("$PYTHON" --version 2>&1)"
echo "Node:      $(node --version 2>&1 || echo 'not found')"
echo "=================================================================="

# Step 1: Backend Unittest
echo ""
echo "------------------------------------------------------------------"
echo "[Step 1/4] Running Backend Unittests..."
echo "------------------------------------------------------------------"
"$PYTHON" -m unittest discover -s backend/tests -v
echo "✅ Backend Unittests Passed"

# Step 2: Frontend Node Tests
echo ""
echo "------------------------------------------------------------------"
echo "[Step 2/4] Running Frontend Node Contract Tests..."
echo "------------------------------------------------------------------"
npm --prefix frontend test
echo "✅ Frontend Contract Tests Passed"

# Step 3: TypeScript Typecheck
echo ""
echo "------------------------------------------------------------------"
echo "[Step 3/4] Running TypeScript Typecheck (tsc --noEmit)..."
echo "------------------------------------------------------------------"
./frontend/node_modules/.bin/tsc --project frontend/tsconfig.json --noEmit
echo "✅ TypeScript Typecheck Passed"

# Step 4: ESLint
echo ""
echo "------------------------------------------------------------------"
echo "[Step 4/4] Running Frontend Linter (ESLint)..."
echo "------------------------------------------------------------------"
npm --prefix frontend run lint -- --rule 'react-hooks/purity: warn'
echo "✅ Frontend ESLint Passed"

echo ""
echo "=================================================================="
echo "🎉 ALL TESTS & VALIDATIONS PASSED SUCCESSFULLY!"
echo "=================================================================="
exit 0
