from math import asin, cos, radians, sin, sqrt

from app.models import Project


EARTH_RADIUS_KM = 6371.0


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    if None in [lat1, lon1, lat2, lon2]:
        return float("inf")

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    lat1_r = radians(lat1)
    lat2_r = radians(lat2)

    a = sin(d_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(d_lon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return EARTH_RADIUS_KM * c


def filter_by_proximity(users, project_lat, project_lon, max_km=25):
    nearby = []
    for user in users:
        if user.latitude is None or user.longitude is None:
            continue
        distance = haversine_distance(project_lat, project_lon, user.latitude, user.longitude)
        if distance <= max_km:
            nearby.append(user)
    return nearby


def get_nearby_projects(lat, lon, max_km=50):
    projects = (
        Project.query.filter_by(is_published=True)
        .filter(Project.status.in_(["assembling", "active"]))
        .all()
    )

    ranked = []
    for project in projects:
        if project.latitude is None or project.longitude is None:
            continue
        distance = haversine_distance(lat, lon, project.latitude, project.longitude)
        if distance <= max_km:
            ranked.append((distance, project))

    ranked.sort(key=lambda item: item[0])
    return [project for _distance, project in ranked]
