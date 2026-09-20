"""SONG-01~03 曲目与场次方案。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..deps import DB, AdminUser, CurrentUser
from ..models import Event, Member, Song
from ..schemas import SongIn, SongListOut, SongOut, SongPatch
from ..services import event_settings, serialize_song, song_durations, song_warnings
from .events import load_event

router = APIRouter(tags=["songs"])


def _resolve_members(db, event: Event, member_ids: list[int]) -> list[Member]:  # noqa: ANN001
    participant_ids = {p.member_id for p in event.participants}
    outside = [i for i in member_ids if i not in participant_ids]
    if outside:
        raise HTTPException(status_code=422, detail=f"成员 {outside} 不是本活动的参与成员,请先在活动中添加")
    members = {m.id: m for m in db.scalars(select(Member).where(Member.id.in_(member_ids))).all()}
    return [members[i] for i in member_ids]


def _check_code(event: Event, code: str, exclude_id: int | None) -> None:
    for s in event.songs:
        if s.id != exclude_id and s.code.lower() == code.lower():
            raise HTTPException(status_code=409, detail=f"代号 {code} 已被曲目「{s.name}」使用")


def _list(event: Event) -> SongListOut:
    settings = event_settings(event)
    songs = [serialize_song(s, settings) for s in event.songs]
    return SongListOut(songs=songs, warnings=song_warnings(event), total_sessions=sum(s.session_count for s in songs))


@router.get("/events/{event_id}/songs", response_model=SongListOut)
def list_songs(event_id: int, db: DB, user: CurrentUser) -> SongListOut:
    return _list(load_event(db, event_id, user))


@router.post("/events/{event_id}/songs", response_model=SongOut, status_code=201)
def create_song(event_id: int, body: SongIn, db: DB, admin: AdminUser) -> SongOut:
    event = load_event(db, event_id, admin)
    _check_code(event, body.code, None)
    members = _resolve_members(db, event, body.member_ids)
    max_order = db.scalar(select(func.max(Song.sort_order)).where(Song.event_id == event.id)) or 0
    song = Song(
        event_id=event.id,
        code=body.code,
        name=body.name,
        difficulty=body.difficulty,
        session_plan=body.session_plan,
        sort_order=max_order + 1,
    )
    song.members = members
    db.add(song)
    db.commit()
    db.refresh(event)
    return serialize_song(song, event_settings(event))


def _get_song(db, song_id: int) -> Song:  # noqa: ANN001
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="曲目不存在")
    return song


@router.patch("/songs/{song_id}", response_model=SongOut)
def update_song(song_id: int, body: SongPatch, db: DB, admin: AdminUser) -> SongOut:
    song = _get_song(db, song_id)
    event = load_event(db, song.event_id, admin)
    if body.code is not None:
        _check_code(event, body.code, song.id)
        song.code = body.code
    if body.name is not None:
        song.name = body.name
    if body.difficulty is not None:
        song.difficulty = body.difficulty
    if body.member_ids is not None:
        song.members = _resolve_members(db, event, body.member_ids)
    if body.clear_session_plan:
        song.session_plan = None
    elif body.session_plan is not None:
        song.session_plan = body.session_plan
    if body.sort_order is not None:
        song.sort_order = body.sort_order
    db.commit()
    db.refresh(event)
    settings = event_settings(event)
    if not song_durations(song, settings):
        raise HTTPException(status_code=422, detail="该难度没有场次模板")
    return serialize_song(song, settings)


@router.delete("/songs/{song_id}", status_code=204)
def delete_song(song_id: int, db: DB, admin: AdminUser) -> None:
    song = _get_song(db, song_id)
    load_event(db, song.event_id, admin)
    db.delete(song)
    db.commit()
