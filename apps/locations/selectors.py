"""Read helpers that load locations and their breadcrumbs in bulk."""

from functools import reduce
from operator import or_

from django.db.models import Q

from .models import Location


def location_payloads(location_ids):
    """Return {location_id: LocationSerializer data} for the given ids.

    Uses two queries in total (the locations, then all of their ancestors)
    instead of two per location. Ids that do not exist are left out, which
    callers treat the same as a missing location.
    """
    from .serializers import LocationSerializer

    ids = {location_id for location_id in location_ids if location_id}
    if not ids:
        return {}

    locations = list(Location.objects.filter(pk__in=ids))
    if not locations:
        return {}

    ancestor_filter = reduce(or_, (
        Q(tree_id=location.tree_id, lft__lte=location.lft, rght__gte=location.rght)
        for location in locations
    ))
    candidates = list(Location.objects.filter(ancestor_filter).order_by("tree_id", "lft"))

    ancestors = {
        location.pk: [
            node for node in candidates
            if node.tree_id == location.tree_id
            and node.lft <= location.lft
            and node.rght >= location.rght
        ]
        for location in locations
    }
    serializer_context = {"location_ancestors": ancestors}
    return {
        location.pk: LocationSerializer(location, context=serializer_context).data
        for location in locations
    }
