"""Offline, reproducible training pipeline for research-only ML models.

Nothing in this package calls a model from a request handler.  Training happens
offline; the FastAPI application only loads a versioned, evaluated artifact.
"""
