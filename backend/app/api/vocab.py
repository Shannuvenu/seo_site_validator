"""Vocabulary metadata route (schema.org types/properties status)."""
from __future__ import annotations

from fastapi import APIRouter

from ..validators.vocabulary import VocabularyProvider

router = APIRouter(tags=["vocabulary"])


@router.get("/vocab/status")
async def vocab_status() -> dict:
    vocab = VocabularyProvider.get()
    return {
        "loaded": vocab.loaded,
        "types": len(vocab.all_types()) if vocab.loaded else 0,
        "properties": len(vocab.all_properties()) if vocab.loaded else 0,
        "error": vocab.load_error,
    }
