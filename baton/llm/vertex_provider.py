"""
llm/vertex_provider.py -- Google Vertex AI (Gemini) backend for baton end.

Lazy-imports ``vertexai`` (google-cloud-aiplatform) so the package is not
required unless the user sets ``llm_provider = "vertex"`` in .baton.toml.

Install with: pip install "baton-cli[vertex]"
Auth:
  - GOOGLE_APPLICATION_CREDENTIALS -- path to service-account JSON key
  - BATON_VERTEX_PROJECT           -- Google Cloud project ID
  - BATON_VERTEX_LOCATION          -- region (default: us-central1)
"""
from __future__ import annotations

import os

from .base import LLMProvider


class VertexProvider(LLMProvider):
    """Google Vertex AI (Gemini) backend.  google-cloud-aiplatform is optional."""

    @property
    def name(self) -> str:
        return "vertex"

    @property
    def default_model(self) -> str:
        return "gemini-1.5-pro"

    def complete(self, system: str, user: str, model: str) -> str:
        """Call the Vertex AI Generative Models API and return the response text."""
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as exc:
            raise RuntimeError(
                "The 'google-cloud-aiplatform' package is required for the "
                "Vertex provider.\n"
                "Install it: pip install \"baton-cli[vertex]\""
            ) from exc

        project = os.environ.get("BATON_VERTEX_PROJECT")
        location = os.environ.get("BATON_VERTEX_LOCATION", "us-central1")

        if not project:
            raise RuntimeError(
                "BATON_VERTEX_PROJECT environment variable is not set.\n"
                "Set it to your Google Cloud project ID:\n"
                "  export BATON_VERTEX_PROJECT=my-gcp-project"
            )

        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.\n"
                "Set it to your service-account JSON key path:\n"
                "  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json"
            )

        vertexai.init(project=project, location=location)

        # Gemini doesn't have a separate system-role param in the same way;
        # prepend the system instructions to the user content.
        combined_prompt = f"{system}\n\n---\n\n{user}"
        vertex_model = GenerativeModel(model)

        try:
            response = vertex_model.generate_content(combined_prompt)
            # Accessing .text raises ValueError on safety-blocked responses.
            text = response.text
        except Exception as exc:
            raise RuntimeError(f"Vertex AI error: {exc}") from exc

        if not text:
            raise RuntimeError(
                "Vertex AI returned no text content in the response."
            )
        return text
