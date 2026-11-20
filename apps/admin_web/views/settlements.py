"""Admin web: import provider settlement files (DANA) and review the result.

Upload -> preview (nothing changed; the file is kept in the session) ->
Import (settles matching paid checkouts, flags the rest for review)."""

import base64

from ..forms import SettlementUploadForm
from ..views_common import *
from apps.core.exceptions import CodedAPIException
from apps.payment_gateway import settlement as settlement_services
from apps.payment_gateway.models import SettlementFile, SettlementLine

SETTLEMENT_PROVIDER = "dana"  # the only provider with a settlement file
SESSION_KEY = "settlement_upload"


def _pending_upload(request):
    upload = request.session.get(SESSION_KEY)
    if not upload:
        return None
    return upload["name"], base64.b64decode(upload["content"])


@platform_admin_required
def settlement_list(request):
    form = SettlementUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        content = upload.read()
        try:
            settlement_services.preview_settlement_file(SETTLEMENT_PROVIDER, upload.name, content)
        except CodedAPIException as error:
            form.add_error("file", error.message)
        else:
            request.session[SESSION_KEY] = {"name": upload.name, "content": base64.b64encode(content).decode()}
            return redirect("admin_web:settlement_preview")
    files = SettlementFile.objects.select_related("imported_by")
    return render(
        request,
        "admin_web/settlements/list.html",
        {"form": form, "page_obj": paginate_admin(files, request)},
    )


@platform_admin_required
def settlement_preview(request):
    pending = _pending_upload(request)
    if pending is None:
        return redirect("admin_web:settlement_list")
    file_name, content = pending
    if request.method == "POST":
        if request.POST.get("action") == "cancel":
            request.session.pop(SESSION_KEY, None)
            messages.info(request, "Import cancelled; nothing was changed.")
            return redirect("admin_web:settlement_list")
        try:
            settlement_file = settlement_services.import_settlement_file(
                request.user, SETTLEMENT_PROVIDER, file_name, content
            )
        except CodedAPIException as error:
            request.session.pop(SESSION_KEY, None)
            messages.error(request, error.message)
            return redirect("admin_web:settlement_list")
        request.session.pop(SESSION_KEY, None)
        messages.success(
            request,
            "Imported: {} settled, {} to review, {} unmatched.".format(
                settlement_file.settled_count, settlement_file.review_count, settlement_file.unmatched_count
            ),
        )
        return redirect("admin_web:settlement_detail", pk=settlement_file.pk)

    try:
        preview = settlement_services.preview_settlement_file(SETTLEMENT_PROVIDER, file_name, content)
    except CodedAPIException as error:
        request.session.pop(SESSION_KEY, None)
        messages.error(request, error.message)
        return redirect("admin_web:settlement_list")
    labels = dict(SettlementLine.Result.choices)
    rows = [
        {
            "line_no": planned.line.line_no,
            "provider_type": planned.line.provider_type,
            "pay_method": planned.line.pay_method,
            "provider_trx_id": planned.line.provider_trx_id,
            "original_trx_id": planned.line.original_trx_id,
            "reference_no": planned.line.reference_no,
            "gateway_payment": planned.gateway_payment,
            "amount": planned.line.amount,
            "fee": planned.line.fee,
            "settle_amount": planned.line.settle_amount,
            "settled_at": planned.line.settled_at,
            "result": planned.result,
            "result_label": labels[planned.result],
            "note": planned.note,
        }
        for planned in preview.lines
    ]
    return render(request, "admin_web/settlements/preview.html", {"preview": preview, "rows": rows})


@platform_admin_required
def settlement_detail(request, pk):
    settlement_file = get_object_or_404(SettlementFile.objects.select_related("imported_by"), pk=pk)
    lines = settlement_file.lines.select_related("gateway_payment")
    result = request.GET.get("result", "")
    if result == "review":
        lines = lines.filter(result__in=SettlementLine.REVIEW_RESULTS)
    elif result in SettlementLine.Result.values:
        lines = lines.filter(result=result)
    return render(
        request,
        "admin_web/settlements/detail.html",
        {
            "settlement_file": settlement_file,
            "page_obj": paginate_admin(lines, request),
            "results": SettlementLine.Result.choices,
            "result": result,
        },
    )
