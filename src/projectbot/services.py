from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Membership, Task, TaskStatus, User, Workspace


async def get_or_create_workspace(
    session: AsyncSession,
    *,
    guild_id: str,
    name: str,
    timezone_name: str = "UTC",
) -> Workspace:
    result = await session.execute(
        select(Workspace).where(Workspace.discord_guild_id == guild_id)
    )
    workspace = result.scalar_one_or_none()
    if workspace:
        # Update name if it changed or was empty
        if workspace.name != name:
            workspace.name = name
        return workspace

    workspace = Workspace(discord_guild_id=guild_id, name=name, timezone=timezone_name)
    session.add(workspace)
    await session.flush()
    return workspace


async def get_or_create_user(
    session: AsyncSession,
    *,
    discord_user_id: str,
    display_name: str,
) -> User:
    result = await session.execute(select(User).where(User.discord_user_id == discord_user_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(discord_user_id=discord_user_id, display_name=display_name)
    session.add(user)
    await session.flush()
    return user


async def ensure_membership(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str = "member",
) -> Membership:
    result = await session.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    membership = result.scalar_one_or_none()
    if membership:
        if membership.role != role:
            membership.role = role
        return membership

    membership = Membership(workspace_id=workspace_id, user_id=user_id, role=role)
    session.add(membership)
    await session.flush()
    return membership


async def create_task(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    title: str,
    description: str | None,
    assignee_user_id: uuid.UUID | None,
    created_by_user_id: uuid.UUID | None,
    due_in_days: int | None,
) -> Task:
    due_at = None
    if due_in_days is not None:
        due_at = datetime.now(timezone.utc) + timedelta(days=due_in_days)

    task = Task(
        workspace_id=workspace_id,
        title=title,
        description=description,
        status=TaskStatus.todo.value,
        due_at=due_at,
        assignee_user_id=assignee_user_id,
        created_by_user_id=created_by_user_id,
    )
    session.add(task)
    await session.flush()
    return task


async def list_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    limit: int = 20,
) -> list[Task]:
    result = await session.execute(
        select(Task)
        .where(Task.workspace_id == workspace_id)
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def find_task_by_prefix(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    task_id_prefix: str,
) -> Task | None:
    result = await session.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            cast(Task.id, String).ilike(f"{task_id_prefix}%"),
        )
    )
    return result.scalars().first()


async def get_task_by_id(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID | str,
) -> Task | None:
    """Get a task by its full ID."""
    if isinstance(task_id, str):
        task_id = uuid.UUID(task_id)

    result = await session.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.id == task_id,
        )
    )
    return result.scalars().first()


async def update_task(
    session: AsyncSession,
    *,
    task: Task,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    assignee_user_id: uuid.UUID | None = ...,  # Use ... as sentinel for "not provided"
) -> Task:
    """Update a task's fields."""
    if title is not None:
        task.title = title
    if description is not None:
        task.description = description
    if status is not None:
        task.status = status
    if assignee_user_id is not ...:  # Only update if explicitly provided
        task.assignee_user_id = assignee_user_id
    await session.flush()
    return task


async def get_user_by_id(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | str,
) -> User | None:
    """Get a user by their ID."""
    if isinstance(user_id, str):
        user_id = uuid.UUID(user_id)

    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalars().first()


async def get_users_by_ids(
    session: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
) -> dict[str, str]:
    """Get display names for multiple users.

    Returns a dict mapping user_id (as string) to display_name.
    """
    if not user_ids:
        return {}

    result = await session.execute(
        select(User).where(User.id.in_(user_ids))
    )
    users = result.scalars().all()

    return {str(user.id): user.display_name for user in users}


def format_task_line(task: Task) -> str:
    task_id = str(task.id)[:8]
    due = task.due_at.astimezone(timezone.utc).date().isoformat() if task.due_at else "-"
    return f"[{task_id}] {task.title} ({task.status}) due={due}"


def format_task_list(tasks: Iterable[Task]) -> str:
    lines = [format_task_line(task) for task in tasks]
    return "\n".join(lines)
