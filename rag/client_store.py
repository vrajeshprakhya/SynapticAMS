"""
rag/client_store.py — Per-client document store for SynapticAMS RAG.

Architecture: file-system-first, zero extra dependencies (stdlib only).
Each client has a directory under clients/{client_id}/ containing:
  config.json        — name, preferred_discipline, style_summary, max_context_docs
  discipline_files/  — .vams custom net/discipline definitions
  style_docs/        — .md/.txt modeling standards and naming conventions
  example_models/    — .va reference models in the client's preferred style

ClientStore.get_context(circuit_hints) returns a formatted string ready for
injection into the AI system prompt as a "## Client-Specific Requirements"
section.  Retrieval is keyword-ranked: documents whose filenames or content
contain words from the circuit_hints are ranked higher.

Upgrade path: drop in a vector-search backend behind the same interface once
per-client corpora grow beyond ~50 documents.
"""

import json
import re
from pathlib import Path

# Root of the clients directory relative to this file's package root.
_CLIENTS_ROOT = Path(__file__).parent.parent / "clients"


class ClientStore:
    """
    Loads and retrieves client-specific context documents.

    Args:
        client_id: identifier matching a subdirectory under clients/.
                   Pass None or an unknown id to get an empty context.
    """

    def __init__(self, client_id: str | None):
        self.client_id = client_id
        self._root = _CLIENTS_ROOT / client_id if client_id else None
        self._config: dict = {}

        if self._root and self._root.is_dir():
            cfg_path = self._root / "config.json"
            if cfg_path.exists():
                try:
                    self._config = json.loads(cfg_path.read_text())
                except json.JSONDecodeError:
                    pass  # malformed config — proceed with empty dict

    @property
    def is_valid(self) -> bool:
        return bool(self._root and self._root.is_dir())

    # ── Public API ─────────────────────────────────────────────────────

    def get_context(self, circuit_hints: dict | None = None) -> str:
        """
        Return a formatted context string for injection into the AI prompt.

        Args:
            circuit_hints: dict with any subset of:
              {module_name, device_types, block_type, signal_source, output_node}
              Used for keyword-ranked retrieval — documents whose filenames or
              content share words with these hints are ranked higher.

        Returns:
            Formatted string starting with "## Client-Specific Requirements"
            or empty string "" if no client is configured.
        """
        if not self.is_valid:
            return ""

        keywords = _extract_keywords(circuit_hints or {})
        sections: list[str] = []

        # ── Config / style summary ────────────────────────────────────
        if self._config:
            summary_parts = []
            if name := self._config.get("name"):
                summary_parts.append(f"Client: {name}")
            if disc := self._config.get("preferred_discipline"):
                summary_parts.append(f"Preferred discipline: {disc}")
            if style := self._config.get("style_summary"):
                summary_parts.append(f"Style notes: {style}")
            if summary_parts:
                sections.append("\n".join(summary_parts))

        # ── Discipline files (.vams custom net definitions) ───────────
        disc_dir = self._root / "discipline_files"
        disc_docs = _load_ranked_docs(disc_dir, keywords,
                                      extensions={".vams", ".va", ".txt", ".md"})
        if disc_docs:
            sections.append("### Custom Discipline / Net Definitions\n" +
                             "\n\n".join(disc_docs))

        # ── Style docs (.md / .txt modeling standards) ────────────────
        style_dir = self._root / "style_docs"
        style_docs = _load_ranked_docs(style_dir, keywords,
                                       extensions={".md", ".txt"})
        if style_docs:
            sections.append("### Modeling Standards & Naming Conventions\n" +
                             "\n\n".join(style_docs))

        # ── Example models (.va reference models) ────────────────────
        max_examples = self._config.get("max_context_docs", 2)
        example_dir = self._root / "example_models"
        example_docs = _load_ranked_docs(example_dir, keywords,
                                         extensions={".va"},
                                         max_docs=max_examples)
        if example_docs:
            sections.append("### Reference Model Examples\n" +
                             "\n\n".join(example_docs))

        if not sections:
            return ""

        header = f"## Client-Specific Requirements ({self._config.get('name', self.client_id)})"
        return header + "\n\n" + "\n\n".join(sections)


# ── Internal helpers ───────────────────────────────────────────────────

def _extract_keywords(hints: dict) -> set[str]:
    """Extract lowercase tokens from circuit_hints for ranking."""
    tokens: set[str] = set()
    for v in hints.values():
        if isinstance(v, str):
            tokens.update(re.split(r"[\W_]+", v.lower()))
        elif isinstance(v, (list, set, tuple)):
            for item in v:
                if isinstance(item, str):
                    tokens.update(re.split(r"[\W_]+", item.lower()))
    return {t for t in tokens if len(t) > 1}  # drop single-char tokens


def _score_doc(path: Path, content: str, keywords: set[str]) -> int:
    """Higher score = more keyword matches in filename + content."""
    text = path.stem.lower() + " " + content.lower()
    return sum(1 for kw in keywords if kw in text)


def _load_ranked_docs(directory: Path,
                      keywords: set[str],
                      extensions: set[str],
                      max_docs: int = 3) -> list[str]:
    """
    Load files from directory, rank by keyword relevance, return top max_docs.
    Each returned entry is: '--- filename ---\\n<content>'.
    """
    if not directory.is_dir():
        return []

    candidates: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if path.suffix.lower() in extensions and path.is_file():
            try:
                content = path.read_text(errors="replace")
                score = _score_doc(path, content, keywords)
                candidates.append((score, path))
            except OSError:
                pass

    # Sort by score descending, then filename for stable tie-breaking
    candidates.sort(key=lambda t: (-t[0], t[1].name))

    results = []
    for _, path in candidates[:max_docs]:
        content = path.read_text(errors="replace").strip()
        results.append(f"--- {path.name} ---\n{content}")
    return results
