from django.urls import path

from . import views

urlpatterns = [
    path("session/", views.SessionView.as_view(), name="customer_session"),
    path("profile/", views.ProfileView.as_view(), name="customer_profile"),
    path("addresses/", views.AddressListView.as_view(), name="customer_addresses"),
    path("addresses/<int:pk>/", views.AddressDetailView.as_view(), name="customer_address"),
    path("orders/", views.OrderListView.as_view(), name="customer_orders"),
]
