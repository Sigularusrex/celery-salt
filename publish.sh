#!/bin/bash

# Clean previous builds
rm -rf dist/

# Make sure we have the latest Poetry
pip install --upgrade poetry

# Build the package
poetry build

# Check the distribution
poetry check

# If a token is provided via environment variable, configure it
if [ ! -z "$PYPI_TOKEN" ]; then
  echo "Configuring PyPI token from environment variable"
  poetry config pypi-token.pypi "$PYPI_TOKEN"
fi

# Prompt user for confirmation before publishing
echo ""
echo "Package built successfully!"
echo "Ready to publish tchu-tchu to PyPI"
echo ""
read -p "Publish to TestPyPI first? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  echo "Publishing to TestPyPI..."
  poetry config repositories.testpypi https://test.pypi.org/legacy/
  poetry publish -r testpypi
  echo ""
  echo "Published to TestPyPI. Test with:"
  echo "pip install --index-url https://test.pypi.org/simple/ tchu-tchu"
  echo ""
fi

read -p "Publish to PyPI? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  echo "Publishing to PyPI..."
  poetry publish
  echo ""
  echo "✅ Successfully published to PyPI!"
  echo "Install with: pip install tchu-tchu"
else
  echo "Skipping PyPI publication"
fi
