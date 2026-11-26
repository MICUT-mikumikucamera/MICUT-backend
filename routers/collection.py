import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

import store
from errors import AppError
from routers.auth import owner
from schemas import Collection, CollectionCard, CollectionPhoto, Job

router = APIRouter(prefix="/api/v1/collection", tags=["collection"])

KST = timezone(timedelta(hours=9))
CARDS = json.loads((Path(__file__).resolve().parent.parent / "cards.json").read_text(encoding="utf-8"))
CARD_IDS = {card["id"] for card in CARDS}


def award(job: Job, card_id: str | None) -> tuple[list[str], list[str]]:
    """AI가 정한 카드를 컬렉션 주인(계정 또는 기기)에 기록한다. (card_ids, new_card_ids)

    card_id가 None이면 컬렉션에 없는 포즈라 카드 없이 갤러리로만 간다.
    """
    if card_id not in CARD_IDS:
        if card_id is not None:
            logging.warning("cards.json에 없는 card_id %r (job %s)", card_id, job.job_id)
        return [], []
    if job.device_id and store.add_acquisition(job.device_id, job.job_id, card_id, datetime.now(KST)):
        return [card_id], [card_id]
    return [card_id], []


@router.get("", response_model=Collection)
def read_collection(owner_id: Annotated[str | None, Depends(owner)]):
    if owner_id is None:  # 로그인도 X-Device-Id도 없음
        raise AppError("INVALID_REQUEST")
    photos = {card["id"]: [] for card in CARDS}
    for card_id, job_id, acquired_at in store.list_acquisitions(owner_id):
        if card_id in photos:  # cards.json에서 빠진 카드의 기록은 무시한다.
            photos[card_id].append(CollectionPhoto(job_id=job_id, acquired_at=acquired_at))
    cards = [
        CollectionCard(**card, photos=sorted(photos[card["id"]], key=lambda p: p.acquired_at))
        for card in sorted(CARDS, key=lambda c: c["no"])
    ]
    return Collection(acquired_count=sum(bool(c.photos) for c in cards), total=len(cards), cards=cards)
