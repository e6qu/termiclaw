#!/usr/bin/env bash
set -euo pipefail

# Count lines of code (excluding blank lines and comments)
code_loc=$(find termiclaw -name '*.py' -not -path '*__pycache__*' -exec cat {} + | grep -cv '^\s*$\|^\s*#')
test_loc=$(find tests -name '*.py' -not -path '*__pycache__*' -exec cat {} + | grep -cv '^\s*$\|^\s*#')

echo "Code: ${code_loc} lines"
echo "Tests: ${test_loc} lines"

# Portable in-place sed (works on both macOS and GNU)
tmp=$(mktemp)
sed "s|\[!\[Code lines\].*|\[!\[Code lines\](https://img.shields.io/badge/code-${code_loc}%20lines-blue)\]|" README.md > "$tmp" && mv "$tmp" README.md
tmp=$(mktemp)
sed "s|\[!\[Test lines\].*|\[!\[Test lines\](https://img.shields.io/badge/tests-${test_loc}%20lines-blue)\]|" README.md > "$tmp" && mv "$tmp" README.md

# Stage the updated README
git add README.md
