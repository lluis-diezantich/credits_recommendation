"""Shared plumbing for the credits-based recommender.

Only the things that were duplicated across scripts and had already drifted
live here: HTTP, name keys, storefront cookies, seen-state. Scoring policy is
deliberately NOT here -- it is in policy.py at the project root, where it is
easy to find and argue about.
"""
