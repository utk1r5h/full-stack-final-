from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register_view, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("items/", views.item_list, name="item_list"),
    path("items/new/", views.item_create, name="item_create"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("private/items/<int:pk>/image/", views.private_item_image, name="private_item_image"),
    path("api/search/", views.live_search, name="live_search"),
    path("claims/<int:pk>/review/", views.claim_review, name="claim_review"),
    path("reports/items.csv", views.export_csv, name="export_csv"),
    path("reports/items.pdf", views.export_pdf, name="export_pdf"),
]
