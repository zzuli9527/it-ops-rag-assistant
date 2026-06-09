from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings, get_settings
from app.service import RagService


def build_eval_settings(base_settings: Settings, temp_root: Path) -> Settings:
    isolated_knowledge_dir = temp_root / "knowledge_docs"
    isolated_knowledge_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.model_validate(
        {
            "data_dir": temp_root / "data",
            "upload_dir": temp_root / "data" / "uploads",
            "db_path": temp_root / "data" / "app.db",
            "sample_docs_dir_override": base_settings.sample_docs_dir,
            "sample_eval_dir_override": base_settings.sample_eval_dir,
            "knowledge_docs_dir_override": isolated_knowledge_dir,
            "retrieval_top_k": base_settings.retrieval_top_k,
            "retrieval_candidates": base_settings.retrieval_candidates,
            "answer_min_score": base_settings.answer_min_score,
            "max_context_chars": base_settings.max_context_chars,
            "llm_mode": base_settings.llm_mode,
            "llm_model": base_settings.llm_model,
            "llm_base_url": base_settings.llm_base_url,
            "llm_api_key": base_settings.llm_api_key,
            "embedding_mode": base_settings.embedding_mode,
            "embedding_model": base_settings.embedding_model,
        }
    )
    settings.ensure_dirs()
    return settings


def main() -> None:
    include_local_docs = "--include-local-docs" in sys.argv[1:]
    base_settings = get_settings()
    if include_local_docs:
        service = RagService(base_settings)
        service.bootstrap(include_knowledge_docs=True)
        result = service.run_evaluation()
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        return

    with tempfile.TemporaryDirectory(prefix="it-ops-rag-eval-") as temp_dir:
        eval_settings = build_eval_settings(base_settings, Path(temp_dir))
        service = RagService(eval_settings)
        service.bootstrap(include_knowledge_docs=False)
        result = service.run_evaluation()
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
