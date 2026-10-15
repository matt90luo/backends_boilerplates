"""Convenience entry point: ``uv run uvicorn main:app --reload``."""

from tinysaas.adapters.web.app import create_app

app = create_app()
