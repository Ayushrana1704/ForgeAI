"""
Checkpoint factory for the ForgeAI workflow graph.

LangGraph checkpointers persist the full graph state between invocations,
enabling fault-tolerance, resumability, and human-in-the-loop pausing.

Development (current)
---------------------
MemorySaver -- in-process dict, zero external dependencies.
Survives within a single process; lost on restart.
Sufficient for unit tests and local development.

Production migration path
--------------------------
Replace MemorySaver with AsyncPostgresSaver backed by the existing
PostgreSQL database (no new infrastructure required):

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.core.config import settings

    async def create_postgres_checkpointer():
        '''
        Async context manager that yields a production-ready checkpointer.
        Call checkpointer.setup() once at application startup to create the
        required tables (langgraph_checkpoints, langgraph_writes, etc.).
        '''
        async with await AsyncPostgresSaver.from_conn_string(
            settings.DATABASE_URL.replace('+asyncpg', '')  # psycopg3 DSN
        ) as checkpointer:
            await checkpointer.setup()
            yield checkpointer

The MemorySaver and AsyncPostgresSaver share the same interface, so
build_forge_graph() requires zero changes when upgrading.
"""
from langgraph.checkpoint.memory import MemorySaver


def create_checkpointer() -> MemorySaver:
    """
    Return a MemorySaver checkpointer for development and testing.

    Usage:
        checkpointer = create_checkpointer()
        graph = build_forge_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": str(run_id)}}
        result = graph.invoke(initial_state, config=config)
    """
    return MemorySaver()
