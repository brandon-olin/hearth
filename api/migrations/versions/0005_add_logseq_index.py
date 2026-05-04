"""Add logseq_index table for graph indexer service

Revision ID: d4f8c1e7a3b9
Revises: c5e3f9a2b1d6
Create Date: 2026-05-04

logseq_index is populated by the graph indexer service that watches the NAS
markdown directories. It is a read index for AI queries — not a source of
truth. The source of truth remains the .md files under /data/logseq/.

Indexes:
  logseq_index_graph_page_name_key  — unique (graph, page_name)
  idx_logseq_index_graph            — btree on graph for per-graph scans
  idx_logseq_index_tags             — GIN on tags[] for tag membership queries
  idx_logseq_index_content_fts      — GIN on to_tsvector(content) for FTS
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "d4f8c1e7a3b9"
down_revision: Union[str, None] = "c5e3f9a2b1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "logseq_index",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("graph", sa.Text(), nullable=False),
        sa.Column("page_name", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("properties", JSONB(), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("block_count", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("graph", "page_name", name="logseq_index_graph_page_name_key"),
    )

    # Fast per-graph scans (most queries are graph-scoped)
    op.create_index("idx_logseq_index_graph", "logseq_index", ["graph"])

    # GIN index on the tags array — supports @> and ANY() membership queries
    op.create_index(
        "idx_logseq_index_tags",
        "logseq_index",
        ["tags"],
        postgresql_using="gin",
    )

    # Functional GIN index for full-text search over page content
    op.create_index(
        "idx_logseq_index_content_fts",
        "logseq_index",
        [sa.text("to_tsvector('english', coalesce(content, ''))")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_logseq_index_content_fts", table_name="logseq_index")
    op.drop_index("idx_logseq_index_tags", table_name="logseq_index")
    op.drop_index("idx_logseq_index_graph", table_name="logseq_index")
    op.drop_table("logseq_index")
