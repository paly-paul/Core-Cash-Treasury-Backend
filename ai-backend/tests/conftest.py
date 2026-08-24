"""Pytest configuration for AI Backend."""
import sys
from pathlib import Path

# Add both app directories to Python path so imports work
backend_path = Path(__file__).parent.parent / "app-backend"
ai_path = Path(__file__).parent
sys.path.insert(0, str(ai_path))
sys.path.insert(0, str(backend_path))
