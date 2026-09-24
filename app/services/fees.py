"""Ориентировочный расчёт въезда в госпарк «Кызылсай» по тарифу с 1.09.2026.

Парк считается один раз, сколько бы его объектов ни было в маршруте.
Транспорт — один въезд на тур, тропа — с человека за каждый день.
Считаем по иностранному тарифу: площадка для иностранных туристов.
Льготы (дети, студенты, пенсионеры) и граждан РК гид уточняет на месте.
"""
from math import ceil

from ..config import (FEE_FOREIGN_MULT, FEE_TRAIL_MRP, FEE_VEHICLE_MRP, MRP, PARK_SITES,
                      SEATS_PER_CAR)


def vehicles(group: int) -> tuple[str, int]:
    if group <= 12:
        return "car", ceil(group / SEATS_PER_CAR)
    if group <= 16:
        return "minibus", 1
    return ("bus", 1) if group <= 32 else ("bus_big", 1)


def compute(site_slugs, group: int, days: int) -> dict | None:
    """None — если маршрут не заходит в парк."""
    if not set(site_slugs) & set(PARK_SITES):
        return None
    person_day = round(FEE_TRAIL_MRP * MRP * FEE_FOREIGN_MULT)
    kind, count = vehicles(group)
    vehicle_price = round(FEE_VEHICLE_MRP[kind] * MRP)
    trail = person_day * group * days
    transport = vehicle_price * count
    return {"person_day": person_day, "group": group, "days": days, "trail": trail,
            "vehicle_kind": kind, "vehicle_count": count, "vehicle_price": vehicle_price,
            "transport": transport, "total": trail + transport}


def client_config() -> dict:
    """Те же константы для живого расчёта в форме заявки."""
    return {"mrp": MRP, "trail": FEE_TRAIL_MRP, "foreign": FEE_FOREIGN_MULT,
            "vehicle": FEE_VEHICLE_MRP, "seats": SEATS_PER_CAR}
