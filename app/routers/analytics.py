"""Дашборды аналитики: финансы площадки и туризм региона, выгрузка отчёта, воронка брони."""
from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..auth import require_user
from ..config import ANALYTICS_PERIODS, APP_NAME
from ..db import pool
from ..services import analytics, funnel, report
from ..web import lang_of, render

router = APIRouter()

# Кто что видит: админ — всё; финансовый админ — только финансы; госнаблюдатель — только
# обезличенные макропоказатели (без имён, контактов и платёжных данных).
FINANCE = ("admin", "finance_admin")
GOV = ("admin", "gov_observer")


@router.get("/dashboard/finance")
async def finance(request: Request, p: str = "quarter"):
    await require_user(request, *FINANCE)
    data = await analytics.finance(pool(), p)
    return await render(request, "dashboard/finance.html", d=data, periods=list(ANALYTICS_PERIODS))


@router.get("/dashboard/gov")
async def gov(request: Request, p: str = "quarter"):
    await require_user(request, *GOV)
    data = await analytics.gov(pool(), p)
    monthly = [{"m": x["m"].isoformat(), "gmv": int(x["gmv"]), "local": int(x["local"])} for x in data["monthly"]]
    return await render(request, "dashboard/gov.html", d=data, periods=list(ANALYTICS_PERIODS), monthly_json=monthly)


@router.get("/dashboard/gov/report.{fmt}")
async def gov_report(request: Request, fmt: str, p: str = "quarter"):
    await require_user(request, *GOV)
    data = await analytics.gov(pool(), p)
    lang = lang_of(request)
    name = f"{APP_NAME.lower()}-tourism-{data['start']:%Y%m%d}-{data['end']:%Y%m%d}"
    if fmt == "xlsx":
        body = report.xlsx(data, lang)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "pdf":
        body = report.pdf(data, lang)
        mime = "application/pdf"
    else:
        return Response(status_code=404)
    return Response(body, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


@router.post("/f/date/{guide_id}")
async def funnel_date(request: Request, guide_id: int):
    await funnel.track(request, "date", guide_id)
    return Response(status_code=204)
