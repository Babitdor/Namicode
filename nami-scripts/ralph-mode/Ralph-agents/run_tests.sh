#!/bin/bash
# Ralph Agents Test Runner
# Runs all tests for the Ralph Agents system

set -e

echo "=========================================="
echo "Ralph Agents Test Suite"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${BLUE}[1/4] Testing Template Validator${NC}"
echo "----------------------------------------"
python template_validator.py --verbose || {
    echo -e "${YELLOW}Some templates may have warnings${NC}"
}

echo ""
echo -e "${BLUE}[2/4] Running Template Structure Tests${NC}"
echo "----------------------------------------"
if command -v pytest &> /dev/null; then
    pytest tests/test_templates.py::TestTemplateStructure -v
else
    echo "pytest not installed. Install with: pip install pytest"
fi

echo ""
echo -e "${BLUE}[3/4] Running Template Validator Tests${NC}"
echo "----------------------------------------"
if command -v pytest &> /dev/null; then
    pytest tests/test_templates.py::TestTemplateValidator -v
else
    echo "pytest not installed. Install with: pip install pytest"
fi

echo ""
echo -e "${BLUE}[4/4] Running Template Utilities Tests${NC}"
echo "----------------------------------------"
if command -v pytest &> /dev/null; then
    pytest tests/test_templates.py::TestTemplateUtils -v
else
    echo "pytest not installed. Install with: pip install pytest"
fi

echo ""
echo -e "${GREEN}=========================================="
echo "Test Suite Complete"
echo "==========================================${NC}"
echo ""
echo "Run specific tests:"
echo "  pytest tests/test_templates.py -v                    # Run all tests"
echo "  pytest tests/test_templates.py::TestTemplateValidator -v  # Specific test class"
echo "  pytest tests/test_templates.py -k 'test_valid_template' -v  # Specific test"
echo ""
echo "Generate analytics:"
echo "  python template_analytics.py --summary --recommendations"
echo ""