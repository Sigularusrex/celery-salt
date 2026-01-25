# Publishing Guide

This document outlines the steps to publish CelerySalt to PyPI.

## Prerequisites

1. **PyPI Account**: Create an account at https://pypi.org/account/register/
2. **TestPyPI Account**: Create an account at https://test.pypi.org/account/register/
3. **Build Tools**: Install build and twine
   ```bash
   pip install build twine
   ```

## Publishing Steps

### 1. Update Version

Update version in:
- `pyproject.toml` - `version = "1.0.0"`
- `celerysalt/version.py` - `__version__ = "1.0.0"`

### 2. Update CHANGELOG.md

Add release notes for the new version.

### 3. Test Build Locally

```bash
# Use publish.sh script (builds and checks package)
./publish.sh
# Answer 'n' to both prompts if you just want to build

# Or manually:
rm -rf dist/ build/ *.egg-info
python -m build
ls -lh dist/
```

### 4. Test on TestPyPI (Recommended)

```bash
# Use publish.sh script - it will prompt for TestPyPI
./publish.sh
# Answer 'y' to "Publish to TestPyPI first?"

# Test installation
pip install --index-url https://test.pypi.org/simple/ celery-salt
```

### 5. Publish to PyPI

```bash
# Use publish.sh script - it will prompt for PyPI
./publish.sh
# Answer 'y' to "Publish to PyPI?"

# Verify installation
pip install celery-salt
```

### 6. Create GitHub Release

1. Go to https://github.com/Sigularusrex/celery-salt/releases
2. Click "Create a new release"
3. Tag: `v1.0.0`
4. Title: `v1.0.0 - Initial Release`
5. Description: Copy from CHANGELOG.md
6. Publish release

### 7. Update Documentation

- Update README.md if needed
- Update any external documentation

## Version Bumping

For future releases:

1. **Patch** (1.0.0 → 1.0.1): Bug fixes
2. **Minor** (1.0.0 → 1.1.0): New features, backward compatible
3. **Major** (1.0.0 → 2.0.0): Breaking changes

Update both:
- `pyproject.toml`
- `celerysalt/version.py`

## Automated Publishing (Future)

Consider setting up GitHub Actions for automated publishing on tag creation.
