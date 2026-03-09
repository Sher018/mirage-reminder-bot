"""Проверка геолокации."""
from math import radians, sin, cos, sqrt, atan2


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя точками в метрах (формула Haversine)."""
    R = 6371000  # радиус Земли в метрах
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def is_location_valid(
    user_lat: float,
    user_lon: float,
    restaurant_lat: float,
    restaurant_lon: float,
    radius_m: int,
) -> bool:
    """Проверяет, что точка в радиусе от ресторана."""
    dist = haversine_distance_m(user_lat, user_lon, restaurant_lat, restaurant_lon)
    return dist <= radius_m
