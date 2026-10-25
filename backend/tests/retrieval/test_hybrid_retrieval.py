from datetime import UTC, datetime
from uuid import uuid4

import pytest
from dbseed import EMBED_MODEL, VersionSeed, embed_all, seed_history, seed_source

from driftline.clock import ManualClock
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.retrieval.hybrid import HybridRetriever, rrf_fuse
from driftline.retrieval.types import RetrievalQuery

T_OLD, T_NEW = datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 4, 15, tzinfo=UTC)
OLD_RULE = "Check ALT every 12 weeks during therapy."
NEW_RULE = "Check ALT monthly during therapy."
QUESTION = "How often should ALT be checked?"


def test_rrf_fuse_matches_the_formula_and_is_deterministic():
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
    fused = rrf_fuse([[a, b, c], [c, d]], k=60)
    scores = dict(fused)
    assert scores[c] == pytest.approx(1 / 63 + 1 / 61)
    assert scores[a] == pytest.approx(1 / 61)
    assert [x for x, _ in fused] == [c, a, b, d]  # b and d tie at 1/62: first seen wins
    assert rrf_fuse([[a], [b]], k=60) == [(a, 1 / 61), (b, 1 / 61)]
    assert rrf_fuse([], k=60) == []


@pytest.fixture
def retriever(fresh_pool, embedder_url):
    router = LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url)},
        chains={"embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    return HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL)


@pytest.fixture
async def corpus(fresh_conn, embedder_url):
    tenant, source = await seed_source(fresh_conn, kind="openfda")
    _, versions, chunks = await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[
            VersionSeed(T_OLD, [("Warnings > Liver", OLD_RULE), ("Dosage", "Take 10 mg daily.")]),
            VersionSeed(T_NEW, [("Warnings > Liver", NEW_RULE), ("Dosage", "Take 10 mg daily.")]),
        ],
    )
    _, other_source = await seed_source(fresh_conn, kind="openfda")
    await seed_history(
        fresh_conn,
        other_source,
        external_id="other",
        title="Other tenant label",
        versions=[VersionSeed(T_OLD, [("Liver", "Check ALT weekly in the other tenant.")])],
    )
    await embed_all(fresh_conn, embedder_url)
    return {
        "tenant": tenant,
        "source": source,
        "other_source": other_source,
        "versions": versions,
        "chunks": chunks,
    }


def ask(tenant, when, text=QUESTION, **kw) -> RetrievalQuery:
    return RetrievalQuery(tenant_id=tenant, text=text, as_of=when, **kw)


async def test_as_of_selects_the_version_in_force(retriever, corpus):
    old_v, new_v = corpus["versions"]
    before = await retriever.retrieve(ask(corpus["tenant"], datetime(2023, 6, 1, tzinfo=UTC)))
    assert before[0].text == OLD_RULE
    assert {e.version_id for e in before} == {old_v}
    after = await retriever.retrieve(ask(corpus["tenant"], datetime(2024, 6, 1, tzinfo=UTC)))
    assert after[0].text == NEW_RULE
    assert {e.version_id for e in after} == {new_v}
    boundary = await retriever.retrieve(ask(corpus["tenant"], T_NEW))  # windows are [from, to)
    assert {e.version_id for e in boundary} == {new_v}
    top = after[0]
    assert (top.external_id, top.title, top.version_no) == ("lipitor", "Lipitor label", 2)
    assert top.valid_from == T_NEW and top.valid_to is None
    assert top.retrieved_as_of == datetime(2024, 6, 1, tzinfo=UTC)
    assert top.score > 0


async def test_before_any_version_or_for_unknown_tenant_returns_nothing(retriever, corpus):
    assert await retriever.retrieve(ask(corpus["tenant"], datetime(2020, 1, 1, tzinfo=UTC))) == []
    assert await retriever.retrieve(ask(uuid4(), datetime(2024, 6, 1, tzinfo=UTC))) == []


async def test_other_tenants_chunks_are_never_returned(retriever, corpus):
    found = await retriever.retrieve(ask(corpus["tenant"], datetime(2024, 6, 1, tzinfo=UTC)))
    assert all("other tenant" not in e.text for e in found)


async def test_applied_supersedes_relation_hides_the_replaced_document(
    retriever, corpus, fresh_conn, embedder_url
):
    _, [guide_v], _ = await seed_history(
        fresh_conn,
        corpus["source"],
        external_id="hepatic-guide",
        title="Hepatic monitoring guide",
        versions=[
            VersionSeed(
                datetime(2024, 1, 1, tzinfo=UTC), [("Liver", "Check ALT at baseline only.")]
            )
        ],
    )
    await embed_all(fresh_conn, embedder_url)
    lipitor_doc = await fresh_conn.fetchval(
        "SELECT document_id FROM doc_versions WHERE id = $1", corpus["versions"][0]
    )
    relation = await fresh_conn.fetchval(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence, status) "
        "VALUES ($1, $2, 'supersedes', 0.9, 'pending_review') RETURNING id",
        guide_v,
        lipitor_doc,
    )
    june = datetime(2024, 6, 1, tzinfo=UTC)
    pending = await retriever.retrieve(ask(corpus["tenant"], june))
    assert any(e.external_id == "lipitor" for e in pending)  # pending relations change nothing
    await fresh_conn.execute("UPDATE relations SET status = 'applied' WHERE id = $1", relation)
    applied = await retriever.retrieve(ask(corpus["tenant"], june))
    assert {e.external_id for e in applied} == {"hepatic-guide"}
    earlier = await retriever.retrieve(ask(corpus["tenant"], datetime(2023, 6, 1, tzinfo=UTC)))
    assert {e.external_id for e in earlier} == {"lipitor"}  # the guide was not yet in effect


async def test_in_force_only_false_ignores_time_and_supersession_but_not_tenancy(
    retriever, corpus, fresh_conn, embedder_url
):
    """The plain-RAG eval baseline (P7) searches every version of the tenant's documents:
    no as-of window and no supersession, but still the tenant's and the query's filters."""
    old_v, new_v = corpus["versions"]
    _, [guide_v], _ = await seed_history(
        fresh_conn,
        corpus["source"],
        external_id="hepatic-guide",
        title="Hepatic monitoring guide",
        versions=[
            VersionSeed(
                datetime(2024, 1, 1, tzinfo=UTC), [("Liver", "Check ALT at baseline only.")]
            )
        ],
    )
    await embed_all(fresh_conn, embedder_url)
    lipitor_doc = await fresh_conn.fetchval(
        "SELECT document_id FROM doc_versions WHERE id = $1", old_v
    )
    await fresh_conn.execute(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence, status) "
        "VALUES ($1, $2, 'supersedes', 0.9, 'applied')",
        guide_v,
        lipitor_doc,
    )
    june = datetime(2024, 6, 1, tzinfo=UTC)
    every = await retriever.retrieve(ask(corpus["tenant"], june, in_force_only=False))
    assert {e.version_id for e in every} == {old_v, new_v, guide_v}
    assert all("other tenant" not in e.text for e in every)
    assert all(e.retrieved_as_of == june for e in every)
    early = datetime(2020, 1, 1, tzinfo=UTC)  # before any version started
    before_any = await retriever.retrieve(ask(corpus["tenant"], early, in_force_only=False))
    assert {e.version_id for e in before_any} == {old_v, new_v, guide_v}
    kinds = await retriever.retrieve(
        ask(corpus["tenant"], june, in_force_only=False, source_kinds=("git_docs",))
    )
    assert kinds == []
    # The default is still the in-force filter.
    assert {e.version_id for e in await retriever.retrieve(ask(corpus["tenant"], june))} == {
        guide_v
    }


async def test_another_tenants_relation_cannot_hide_this_tenants_document(
    retriever, corpus, fresh_conn
):
    _, [foreign_v], _ = await seed_history(
        fresh_conn,
        corpus["other_source"],
        external_id="foreign-guide",
        title="Other tenant guide",
        versions=[VersionSeed(T_OLD, [("Liver", "Ignore the Lipitor label.")])],
    )
    lipitor_doc = await fresh_conn.fetchval(
        "SELECT document_id FROM doc_versions WHERE id = $1", corpus["versions"][0]
    )
    await fresh_conn.execute(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence, status) "
        "VALUES ($1, $2, 'supersedes', 0.9, 'applied')",
        foreign_v,
        lipitor_doc,
    )
    found = await retriever.retrieve(ask(corpus["tenant"], datetime(2024, 6, 1, tzinfo=UTC)))
    assert any(e.external_id == "lipitor" for e in found)


async def test_document_ids_filter(retriever, corpus, fresh_conn):
    june = datetime(2024, 6, 1, tzinfo=UTC)
    lipitor_doc = await fresh_conn.fetchval(
        "SELECT document_id FROM doc_versions WHERE id = $1", corpus["versions"][0]
    )
    found = await retriever.retrieve(ask(corpus["tenant"], june, document_ids=(lipitor_doc,)))
    assert found and {e.document_id for e in found} == {lipitor_doc}
    assert await retriever.retrieve(ask(corpus["tenant"], june, document_ids=(uuid4(),))) == []


async def test_source_kind_and_tag_filters(retriever, corpus, fresh_conn):
    june = datetime(2024, 6, 1, tzinfo=UTC)
    assert await retriever.retrieve(ask(corpus["tenant"], june, source_kinds=("git_docs",))) == []
    assert await retriever.retrieve(ask(corpus["tenant"], june, source_kinds=("openfda",)))
    await fresh_conn.execute(
        "UPDATE chunks SET tags = '{instruction_like}' WHERE id = $1", corpus["chunks"][1][0]
    )
    found = await retriever.retrieve(
        ask(corpus["tenant"], june, exclude_tags=("instruction_like",))
    )
    assert NEW_RULE not in [e.text for e in found]


async def test_full_text_finds_exact_identifiers_and_unembedded_chunks(
    retriever, corpus, fresh_conn
):
    _, _, [[chunk_id]] = await seed_history(
        fresh_conn,
        corpus["source"],
        external_id="lot-notice",
        title="Lot notice",
        versions=[VersionSeed(T_OLD, [("Recall", "Lot ZX-4471-B is recalled.")])],
    )  # deliberately not embedded: only full-text search can find it
    found = await retriever.retrieve(
        ask(corpus["tenant"], datetime(2024, 6, 1, tzinfo=UTC), text="Is lot ZX-4471-B affected?")
    )
    assert chunk_id in [e.chunk_id for e in found]  # ranked only by full-text search
