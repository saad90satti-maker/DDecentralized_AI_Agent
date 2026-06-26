"""GitHub operations — repository structure, CI/CD for DAIOS."""

DAIOS_GITIGNORE = """# DAIOS — Git ignore rules
__pycache__/
*.pyc
*.pyo
.env
venv/
.venv/
*.egg-info/
dist/
build/
*.log
daios/data/checkpoints/*
*.db
*.sqlite3
.DS_Store
Thumbs.db
"""

DAIOS_WORKFLOW = """name: DAIOS CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: python -m pytest tests/ -v
      - name: Lint
        run: python -m flake8 daios/ --max-line-length=100 || true

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build and push Docker image
        run: |
          docker build -t daios:latest .
"""

GITHUB_STRUCTURE = """
daios/
├── .github/workflows/ci.yml
├── daios/                    # Main source
├── tests/                    # Test suite
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── setup.py
└── README.md
"""
