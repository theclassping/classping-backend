from ..views_common import *

@login_required(login_url="admin_web:login")
def payment_list(request):
    payments = Payment.objects.select_related(
        "student_invoice__class_student__student",
        "student_invoice__class_student__class_obj__branch",
        "verified_by__user",
    )
    status_filter = request.GET.get("status", "")
    school_id = request.GET.get("school", "")
    branch_id = request.GET.get("branch", "")
    class_id = request.GET.get("class_obj", "")
    search = request.GET.get("q", "").strip()
    if status_filter in Payment.Status.values:
        payments = payments.filter(status=status_filter)
    if school_id:
        payments = payments.filter(student_invoice__class_student__class_obj__branch__school_id=school_id)
    if branch_id:
        payments = payments.filter(student_invoice__class_student__class_obj__branch_id=branch_id)
    if class_id:
        payments = payments.filter(student_invoice__class_student__class_obj_id=class_id)
    if search:
        payments = payments.filter(
            Q(student_invoice__invoice_no__icontains=search)
            | Q(student_invoice__class_student__student__first_name__icontains=search)
            | Q(student_invoice__class_student__student__last_name__icontains=search)
        )
    return render(
        request,
        "admin_web/payments/list.html",
        {
            "payments": payments,
            "status_filter": status_filter,
            "search": search,
            "statuses": Payment.Status.choices,
            "school_id": school_id, "branch_id": branch_id, "class_id": class_id,
            "schools": School.objects.order_by("name"),
            "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
            "classes": Class.objects.select_related("branch__school").order_by("branch__school__name", "branch__name", "name"),
        },
    )


@login_required(login_url="admin_web:login")
def payment_form(request, pk=None):
    payment = get_object_or_404(Payment, pk=pk) if pk else None
    if payment and payment.status != Payment.Status.SUBMITTED:
        messages.error(request, "Only submitted, unverified payments can be edited.")
        return redirect("admin_web:payment_detail", pk=payment.pk)
    form = PaymentForm(request.POST or None, instance=payment)
    proof_formset = PaymentProofFormSet(
        request.POST or None,
        instance=payment,
        prefix="proofs",
    )
    if request.method == "POST" and form.is_valid() and proof_formset.is_valid():
        with transaction.atomic():
            payment = form.save()
            proof_formset.instance = payment
            proof_formset.save()
            invoice = payment.student_invoice
            if invoice.status == StudentInvoice.Status.UNPAID:
                invoice.status = StudentInvoice.Status.PAYMENT_SUBMITTED
                invoice.save(update_fields=["status", "updated_at"])
        messages.success(request, "Payment saved.")
        return redirect("admin_web:payment_detail", pk=payment.pk)
    return render(
        request,
        "admin_web/payments/form.html",
        {"form": form, "proof_formset": proof_formset, "payment": payment},
    )


@login_required(login_url="admin_web:login")
def payment_delete(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("student_invoice"), pk=pk)
    if request.method != "POST":
        return redirect("admin_web:payment_detail", pk=pk)
    if payment.status != Payment.Status.SUBMITTED:
        messages.error(request, "Reviewed payments are retained for audit and cannot be deleted.")
        return redirect("admin_web:payment_detail", pk=pk)
    with transaction.atomic():
        invoice = StudentInvoice.objects.select_for_update().get(pk=payment.student_invoice_id)
        payment.delete()
        if invoice.status == StudentInvoice.Status.PAYMENT_SUBMITTED:
            invoice.status = StudentInvoice.Status.UNPAID
            invoice.save(update_fields=["status", "updated_at"])
    messages.success(request, "Unverified payment and its proofs were deleted.")
    return redirect("admin_web:payment_list")


@login_required(login_url="admin_web:login")
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related(
            "student_invoice__class_student__student",
            "student_invoice__class_student__class_obj__branch",
            "student_invoice__fee_type",
            "verified_by__user",
        ).prefetch_related("proofs"),
        pk=pk,
    )
    return render(
        request,
        "admin_web/payments/detail.html",
        {"payment": payment, "can_review": hasattr(request.user, "staff")},
    )


@login_required(login_url="admin_web:login")
def payment_review(request, pk, action):
    payment = get_object_or_404(Payment.objects.select_related("student_invoice"), pk=pk)
    staff = getattr(request.user, "staff", None)
    if not staff:
        messages.error(request, "A staff profile is required to review payments.")
        return redirect("admin_web:payment_detail", pk=pk)
    if request.method != "POST" or payment.status != Payment.Status.SUBMITTED:
        messages.error(request, "Only submitted payments can be reviewed.")
        return redirect("admin_web:payment_detail", pk=pk)

    if action == "reject":
        form = PaymentRejectionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Enter a reason before rejecting this payment.")
            return redirect("admin_web:payment_detail", pk=pk)
    elif action != "approve":
        return HttpResponseForbidden()

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=pk)
        invoice = StudentInvoice.objects.select_for_update().get(
            pk=payment.student_invoice_id
        )
        if payment.status != Payment.Status.SUBMITTED:
            messages.error(request, "This payment has already been reviewed.")
            return redirect("admin_web:payment_detail", pk=pk)
        payment.verified_by = staff
        payment.verified_at = timezone.now()
        if action == "approve":
            payment.status = Payment.Status.COMPLETED
            payment.paid_at = payment.verified_at
            invoice.status = StudentInvoice.Status.PAID
            invoice.amount_paid = payment.amount
            messages.success(request, "Payment approved and invoice marked paid.")
        else:
            payment.status = Payment.Status.REJECTED
            payment.rejection_reason = form.cleaned_data["rejection_reason"]
            invoice.status = StudentInvoice.Status.UNPAID
            messages.success(request, "Payment rejected.")
        payment.save(
            update_fields=[
                "status", "verified_by", "verified_at", "paid_at",
                "rejection_reason", "updated_at",
            ]
        )
        invoice.save(update_fields=["status", "amount_paid", "updated_at"])
    return redirect("admin_web:payment_detail", pk=pk)


@login_required(login_url="admin_web:login")
def student_invoice_list(request):
    invoices = StudentInvoice.objects.select_related(
        "class_student__student", "class_student__class_obj__branch__school",
        "class_student__class_obj__academic_year", "fee_type",
    ).order_by("-invoice_date", "-pk")
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    school_id = request.GET.get("school", "")
    branch_id = request.GET.get("branch", "")
    class_id = request.GET.get("class_obj", "")
    if search:
        invoices = invoices.filter(
            Q(invoice_no__icontains=search)
            | Q(class_student__student__first_name__icontains=search)
            | Q(class_student__student__last_name__icontains=search)
            | Q(fee_type__name__icontains=search)
        )
    if status in StudentInvoice.Status.values:
        invoices = invoices.filter(status=status)
    if school_id:
        invoices = invoices.filter(class_student__class_obj__branch__school_id=school_id)
    if branch_id:
        invoices = invoices.filter(class_student__class_obj__branch_id=branch_id)
    if class_id:
        invoices = invoices.filter(class_student__class_obj_id=class_id)
    page_obj = Paginator(invoices, 25).get_page(request.GET.get("page"))
    return render(request, "admin_web/student_invoices/list.html", {
        "page_obj": page_obj, "search": search, "status": status,
        "school_id": school_id, "branch_id": branch_id, "class_id": class_id,
        "schools": School.objects.order_by("name"),
        "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
        "classes": Class.objects.select_related("branch__school").order_by("branch__school__name", "branch__name", "name"),
        "statuses": StudentInvoice.Status.choices,
    })


@login_required(login_url="admin_web:login")
def student_invoice_detail(request, pk):
    invoice = get_object_or_404(
        StudentInvoice.objects.select_related(
            "class_student__student", "class_student__class_obj__branch__school",
            "class_student__class_obj__academic_year", "fee_type",
        ).prefetch_related("payment__proofs"), pk=pk,
    )
    return render(request, "admin_web/student_invoices/detail.html", {"invoice": invoice})

