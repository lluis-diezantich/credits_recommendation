"""Shared plumbing for the credits-based recommender.

Only the things that were duplicated across scripts and had already drifted
live here: HTTP, name keys, storefront cookies, seen-state.

Scoring policy is deliberately NOT here. It lived in policy.py at the project
root, where it was easy to find and argue about; D41 archived that file onto
the `ranking` branch along with everything that read it, so nothing on main
holds a contestable number except the radar's own cron and window.
"""
