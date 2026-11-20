from django.urls import path
from django.contrib import admin
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("demo/create/", views.demo_create, name="demo-create"),
    path("demo/<int:pk>/", views.demo_detail, name="demo-detail"),
    path('admin/', admin.site.urls),
]
