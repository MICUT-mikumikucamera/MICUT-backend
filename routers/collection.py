import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header

import store
from schemas import DEVICE_ID, Collection, CollectionCard, CollectionPhoto, Job

router = APIRouter(prefix="/api/v1/collection", tags=["collection"])

KST = timezone(timedelta(hours=9))
CARDS = json.loads((Path(__file__).resolve().parent.parent / "cards.json").read_text(encoding="utf-8"))


def award(job: Job) -> tuple[list[str], list[str]]:
    """done이 된 작업에 카드를 정하고 기기 컬렉션에 기록한다. (card_ids, new_card_ids)"""
    # ponytail: 무작위 카드. AI가 미쿠의 포즈를 알려 주면 그 포즈의 카드로 교체
    card_id = random.choice(CARDS)["id"]
    if job.device_id and store.add_acquisition(job.device_id, job.job_id, card_id, datetime.now(KST)):
        return [card_id], [card_id]
    return [card_id], []


@router.get("", response_model=Collection)
def read_collection(x_device_id: Annotated[str, Header(pattern=DEVICE_ID)]):
    photos = {card["id"]: [] for card in CARDS}
    for card_id, job_id, acquired_at in store.list_acquisitions(x_device_id):
        if card_id in photos:  # cards.json에서 빠진 카드의 기록은 무시한다.
            photos[card_id].append(CollectionPhoto(job_id=job_id, acquired_at=acquired_at))
    cards = [
        CollectionCard(**card, photos=sorted(photos[card["id"]], key=lambda p: p.acquired_at))
        for card in sorted(CARDS, key=lambda c: c["no"])
    ]
    return Collection(acquired_count=sum(bool(c.photos) for c in cards), total=len(cards), cards=cards)
