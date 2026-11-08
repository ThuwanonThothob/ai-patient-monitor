#!/usr/bin/env bash
# ==============================================================================
# Unified Automated Test Runner for Smart Ward AI Patient Monitor
# Steps:
#   0. Bootstrap Test Fixtures (BIDMC / PMD / Models for Clean CI Checkouts)
#   1. Backend Unittests (backend/tests + scripts/tests)
#   2. Frontend Node Contract & Adversarial Tests
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

# Step 0: Bootstrap Test Fixtures (idempotent; no-op when real data/models exist)
echo ""
echo "------------------------------------------------------------------"
echo "[Step 0/5] Ensuring Reproducible Test Fixtures & Model Artifacts..."
echo "------------------------------------------------------------------"
"$PYTHON" scripts/bootstrap_test_fixtures.py
echo "✅ Test Fixtures Verified"

# Step 1a: Backend Unittests
echo ""
echo "------------------------------------------------------------------"
echo "[Step 1/5] Running Backend Unittests (backend/tests)..."
echo "------------------------------------------------------------------"
"$PYTHON" -m unittest discover -s backend/tests -p "test_*.py" -v
echo "✅ Backend Unittests Passed"

# Step 1b: Scripts Unittests
echo ""
echo "------------------------------------------------------------------"
echo "[Step 2/5] Running Scripts Unittests (scripts/tests)..."
echo "------------------------------------------------------------------"
"$PYTHON" -m unittest discover -s scripts/tests -p "test_*.py" -v
echo "✅ Scripts Unittests Passed"

# Step 2: Frontend Node Tests
echo ""
echo "------------------------------------------------------------------"
echo "[Step 3/5] Running Frontend Node Contract & Adversarial Tests..."
echo "------------------------------------------------------------------"
(cd frontend && npm test)
echo "✅ Frontend Contract & Adversarial Tests Passed"

# Step 3: TypeScript Typecheck
echo ""
echo "------------------------------------------------------------------"
echo "[Step 4/5] Running TypeScript Typecheck (tsc --noEmit)..."
echo "------------------------------------------------------------------"
(cd frontend && npx tsc --noEmit)
echo "✅ TypeScript Typecheck Passed"

# Step 4: ESLint
echo ""
echo "------------------------------------------------------------------"
echo "[Step 5/5] Running Frontend Linter (ESLint)..."
echo "------------------------------------------------------------------"
(cd frontend && npm run lint -- --rule 'react-hooks/purity: warn')
echo "✅ Frontend ESLint Passed"

echo ""
echo "=================================================================="
echo "🎉 ALL TESTS & VALIDATIONS PASSED SUCCESSFULLY!"
echo "=================================================================="
exit 0
