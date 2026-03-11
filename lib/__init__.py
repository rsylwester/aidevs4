"""Shared utilities package."""

import warnings

# langchain-core internally imports pydantic.v1 for backwards compat — harmless on Python 3.14
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality", category=UserWarning)
