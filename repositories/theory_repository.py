from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Theory


class TheoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_theory(self, theory_data: dict):
        new_theory = Theory(**theory_data)
        self.db.add(new_theory)
        await self.db.commit()
        # expire_on_commit=False preserves object state; refresh() is unnecessary
        return new_theory

    async def update_theory(self, theory: Theory, update_data: dict):
        for key, value in update_data.items():
            setattr(theory, key, value)
        await self.db.commit()
        # expire_on_commit=False preserves object state; refresh() is unnecessary
        return theory

    async def delete_theory(self, theory: Theory):
        await self.db.delete(theory)
        await self.db.commit()
    
    async def get_all_topics(self):
        r = await self.db.execute(select(Theory.topic).distinct())
        return r.all()
    
    async def get_all_theory(self):
        """Получить весь теоретический материал"""
        r = await self.db.execute(
            select(Theory).order_by(Theory.theory_class, Theory.priority, Theory.topic, Theory.section)
        )
        return r.scalars().all()
    
    async def get_theory_by_topic(self, topic: str):
        r = await self.db.execute(
            select(Theory)
            .where(Theory.topic == topic)
            .order_by(Theory.priority, Theory.section)
        )
        return r.scalars().all()
    
    async def get_theory_by_topic_and_section(self, topic: str, section: str, theory_class: int | None = None):
        stmt = select(Theory).where(
            Theory.topic == topic,
            Theory.section == section,
        )
        if theory_class is not None:
            stmt = stmt.where(Theory.theory_class == theory_class)
        r = await self.db.execute(stmt)
        return r.scalars().first()
    
    async def get_theory_by_id(self, theory_id: int):
        r = await self.db.execute(
            select(Theory).where(Theory.id == theory_id)
        )
        return r.scalars().first()
    
    async def get_topic_section_pairs(self):
        """Уникальные пары (topic, section) для мета-структуры."""
        r = await self.db.execute(
            select(Theory.topic, Theory.section)
            .where(Theory.topic.is_not(None))
            .order_by(Theory.topic, Theory.section)
            .distinct()
        )
        return r.all()

    async def get_theory_meta_rows(self):
        """id + topic + section + class + priority без content."""
        r = await self.db.execute(
            select(
                Theory.id,
                Theory.topic,
                Theory.section,
                Theory.theory_class,
                Theory.priority,
            )
            .where(Theory.topic.is_not(None))
            .order_by(Theory.theory_class, Theory.priority, Theory.topic, Theory.section)
        )
        return r.all()

    async def get_theory_sections_count(self, topic: str) -> int:
        r = await self.db.execute(
            select(func.count(Theory.id)).where(Theory.topic == topic)
        )
        return r.scalar() or 0