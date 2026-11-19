from django.urls import path

from . import views

app_name = "plan_subscriptions"

urlpatterns = [
    path("", views.SubscriptionView.as_view(), name="subscription"),
    path("plans/", views.PlanListView.as_view(), name="plans"),
    path("subscribe/", views.SubscribeView.as_view(), name="subscribe"),
    path("change-plan/", views.ChangePlanView.as_view(), name="change-plan"),
    path("cancel/", views.CancelView.as_view(), name="cancel"),
    path("addons/", views.AddonListView.as_view(), name="addons"),
    path("addons/quote/", views.AddonQuoteView.as_view(), name="addon-quote"),
    path("addons/<int:pk>/", views.AddonDetailView.as_view(), name="addon-detail"),
    path("invoices/", views.InvoiceListView.as_view(), name="invoices"),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice-detail"),
    path("invoices/<int:pk>/channels/", views.InvoiceChannelsView.as_view(), name="invoice-channels"),
    path("invoices/<int:pk>/checkout/", views.InvoiceCheckoutView.as_view(), name="invoice-checkout"),
    path("payments/<int:pk>/", views.PaymentDetailView.as_view(), name="payment-detail"),
    path("payments/<int:pk>/cancel/", views.PaymentCancelView.as_view(), name="payment-cancel"),
]
