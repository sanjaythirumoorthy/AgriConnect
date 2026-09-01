"""
AI Shared Transportation Optimizer
------------------------------------
Groups pending farmer shipments into shared truck loads to cut cost.
Approach (MVP -- upgrade path to Google OR-Tools VRP noted below):
  1. Cluster shipments by geographic proximity (simple radius-based
     greedy clustering on lat/lon -- no need for sklearn's KMeans
     since cluster *count* isn't known ahead of time).
  2. Within each geo-cluster, greedily bin-pack shipments into trucks
     up to TRUCK_CAPACITY_KG, prioritizing filling a truck over
     starting a new one (reduces number of trips = reduces cost).
  3. Estimate per-farmer cost share proportional to their weight in
     the combined load, with a discount vs. going solo.

Upgrade path: replace step 1+2 with Google OR-Tools' Capacitated
Vehicle Routing Problem (CVRP) solver for true route-optimal grouping
once shipment volume justifies it.
"""
import math

TRUCK_CAPACITY_KG = 1000
SOLO_RATE_PER_KG = 6.0      # cost/kg if a farmer ships alone
SHARED_RATE_PER_KG = 3.5    # cost/kg once pooled into a shared truck
CLUSTER_RADIUS_KM = 25


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def optimize_shipments(shipments: list[dict]):
    """shipments: list of dicts with id, farmer_name, product, quantity_kg, lat, lon.
    Returns list of shipment groups (each a combined truck load)."""
    unclustered = shipments[:]
    clusters = []

    while unclustered:
        seed = unclustered.pop(0)
        cluster = [seed]
        remaining = []
        for s in unclustered:
            dist = _haversine_km(seed["lat"], seed["lon"], s["lat"], s["lon"])
            if dist <= CLUSTER_RADIUS_KM:
                cluster.append(s)
            else:
                remaining.append(s)
        unclustered = remaining
        clusters.append(cluster)

    groups = []
    for cluster in clusters:
        cluster = sorted(cluster, key=lambda s: -s["quantity_kg"])
        trucks = []
        for s in cluster:
            placed = False
            for truck in trucks:
                load = sum(i["quantity_kg"] for i in truck)
                if load + s["quantity_kg"] <= TRUCK_CAPACITY_KG:
                    truck.append(s)
                    placed = True
                    break
            if not placed:
                trucks.append([s])

        for truck in trucks:
            total_kg = sum(i["quantity_kg"] for i in truck)
            solo_total_cost = sum(i["quantity_kg"] * SOLO_RATE_PER_KG for i in truck)
            shared_total_cost = total_kg * SHARED_RATE_PER_KG
            savings = round(solo_total_cost - shared_total_cost, 2)
            per_farmer = []
            for i in truck:
                share = round((i["quantity_kg"] / total_kg) * shared_total_cost, 2) if total_kg else 0
                per_farmer.append({**i, "cost_share": share})
            groups.append({
                "farmers": per_farmer,
                "total_kg": total_kg,
                "truck_count": 1,
                "shared_total_cost": round(shared_total_cost, 2),
                "estimated_savings": max(savings, 0),
            })

    return groups
