"""Document intake service for a RAG system.

The write path: accepts documents over HTTP, enforces domain rules, persists
them, and publishes a `DocumentIngested` event through a transactional outbox.
"""
