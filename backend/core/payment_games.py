"""Payment schedule identity. No Daily Sheet dependencies or historical inference."""
import re
from datetime import date
from django.core.exceptions import ValidationError as ModelValidationError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Agency, PaymentObligation
from .holiday_overrides import effective_schedule_for_date


def strict_date(value):
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValidationError({"business_date": "Use an ISO date in YYYY-MM-DD format."})
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({"business_date": "Use a valid calendar date."})


def effective_games(business_date):
    # A date-only value is the Africa/Accra business day, never a UTC conversion.
    business_date = strict_date(business_date)
    try:
        entries, override = effective_schedule_for_date(business_date)
    except ModelValidationError as exc:
        raise ValidationError(exc.message_dict)
    return [{"game_id": entry.game.pk, "name": entry.game.name, "category": entry.category,
             "business_date": business_date.isoformat(), "weekday": business_date.isoweekday(),
             "is_whole_day": entry.is_whole_day,
             "closing_time": entry.closing_time.isoformat() if entry.closing_time else None,
             "draw_time": entry.draw_time.isoformat() if entry.draw_time else None,
             "holiday_override_applied": entry.is_holiday_override,
             "holiday_override_id": override.pk if entry.is_holiday_override else None,
             "holiday_name": override.holiday_name if entry.is_holiday_override else None,
             "source_game_id": override.normal_game_id if entry.is_holiday_override else None,
             "source_game_name": override.normal_game.name if entry.is_holiday_override else None,
             "source_date": override.source_date.isoformat() if entry.is_holiday_override else None}
            for entry in entries]


def resolve_game_snapshot(game_id, business_date):
    result = next((row for row in effective_games(business_date) if row["game_id"] == game_id), None)
    if result is None:
        raise ValidationError({"game": "Select an active effective game for this business date."})
    return result


class PaymentEffectiveGamesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, agency_id):
        from .views import ensure_agency_filter_access
        ensure_agency_filter_access(request.user, [agency_id])
        get_object_or_404(Agency, pk=agency_id, is_active=True)
        if set(request.query_params) != {"business_date"} or len(request.query_params.getlist("business_date")) != 1:
            raise ValidationError({"business_date": "Supply exactly one business_date parameter."})
        fields = ("game_id", "name", "category", "business_date", "is_whole_day", "closing_time", "draw_time", "holiday_override_applied", "holiday_name")
        return Response([{key: row[key] for key in fields} for row in effective_games(request.query_params.get("business_date"))])


def duplicate_guard(agency, number, game, business_date):
    existing = PaymentObligation.objects.filter(agency=agency, sub_agent_number=number,
        business_date=business_date, game_id_snapshot=game.pk).first()
    if existing:
        if existing.status == "CANCELLED":
            message = "A cancelled obligation exists for this number, game and date. Replacement is not permitted; contact an administrator."
        else:
            message = f"An obligation already exists for Sub-Agent Number {number.code}, {existing.game_snapshot['name']} on {business_date}. Open the existing obligation to record payment."
        raise ValidationError({"game": message, "existing_obligation_id": existing.pk})


def filter_games(queryset, params, prefix=""):
    game = params.get("game")
    if game:
        if not str(game).isdigit() or len(str(game)) > 18:
            raise ValidationError({"game": "Use a numeric game ID."})
        queryset = queryset.filter(**{prefix + "game_id_snapshot": int(game)})
    name = params.get("game_name")
    if name:
        if len(name) > 200:
            raise ValidationError({"game_name": "Game search is too long."})
        queryset = queryset.filter(**{prefix + "game_snapshot__name__icontains": name})
    category = params.get("game_category")
    if category:
        if category not in {"TIMED", "GHANA", "DOUBLE_CHANCE"}:
            raise ValidationError({"game_category": "Unsupported category."})
        queryset = queryset.filter(**{prefix + "game_snapshot__category": category})
    for field, lookup in (("business_date", ""), ("business_start", "__gte"), ("business_end", "__lte")):
        if params.get(field):
            queryset = queryset.filter(**{prefix + "business_date" + lookup: strict_date(params[field])})
    if params.get("business_start") and params.get("business_end") and params["business_start"] > params["business_end"]:
        raise ValidationError({"business_end": "End must be on or after start."})
    if params.get("weekday"):
        if params["weekday"] not in list("1234567"):
            raise ValidationError({"weekday": "Use ISO weekday 1 through 7."})
        queryset = queryset.filter(**{prefix + "game_snapshot__weekday": int(params["weekday"])})
    if params.get("holiday_override"):
        if params["holiday_override"] not in {"true", "false"}:
            raise ValidationError({"holiday_override": "Use true or false."})
        queryset = queryset.filter(**{prefix + "game_snapshot__holiday_override_applied": params["holiday_override"] == "true"})
    return queryset


def game_breakdown(obligations, payments, request):
    from .payment_numbers import NumberPagination, totals
    dimensions = {"game": "game_id_snapshot", "category": "game_snapshot__category",
        "business_date": "business_date", "weekday": "game_snapshot__weekday", "agency": "agency_id",
        "payer": "payer_id", "sub_agent_number": "sub_agent_number_snapshot", "terminal_number": "terminal_number_snapshot"}
    group = request.query_params.get("group_by", "game")
    if group not in dimensions:
        raise ValidationError({"group_by": "Unsupported game analytics grouping."})
    field = dimensions[group]
    groups = obligations.order_by(field).values_list(field, flat=True).distinct()
    paginator = NumberPagination()
    paginator.page_query_param = "game_page"
    result = []
    for value in paginator.paginate_queryset(groups, request):
        selected = obligations.filter(**{field: value}) if value is not None else obligations.filter(**{field + "__isnull": True})
        latest = selected.order_by("-pk").first()
        result.append({"group": value, "game_snapshot": latest.game_snapshot,
                       **totals(selected, payments.filter(obligation__in=selected))})
    return {"group_by": group, "count": paginator.page.paginator.count,
            "next": paginator.get_next_link(), "previous": paginator.get_previous_link(), "results": result}


def receipt_game_rows(snapshot):
    if not snapshot:
        return [("Game", "Not assigned - legacy obligation.")]
    return [("Game", snapshot["name"]), ("Game category", {"TIMED": "Timed", "GHANA": "Ghana Game", "DOUBLE_CHANCE": "Double Chance"}[snapshot["category"]]),
            ("Game business date", snapshot["business_date"]),
            ("Game schedule", "Whole Day" if snapshot["is_whole_day"] else f"Closing {snapshot['closing_time']} / Draw {snapshot['draw_time']}"),
            ("Holiday Game", snapshot["holiday_name"] if snapshot["holiday_override_applied"] else "No")]
