"""Reusable subscriptions for Django.

The package knows nothing about what a feature means. A host project:

* points ``PLAN_SUBSCRIPTIONS_SUBSCRIBER_MODEL`` at the model that subscribes,
* loads its own catalog (features, plans, add-ons) with ``catalog.load_catalog``,
* asks ``entitlements`` before doing anything a plan limits,
* plugs in a billing backend and a notifier through ``PLAN_SUBSCRIPTIONS``.
"""

from .notify import notifications_disabled  # noqa: F401
