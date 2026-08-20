"""Корневая карта адресов проекта FinControl."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from finance.views import SignUpView, SitePasswordChangeView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/signup/', SignUpView.as_view(), name='signup'),

    # Свои шаблоны смены пароля объявлены до include: у django.contrib.admin
    # есть свои registration/password_change_form.html, и её приложение стоит
    # раньше в INSTALLED_APPS, поэтому иначе побеждают шаблоны админки
    path(
        'accounts/password_change/',
        SitePasswordChangeView.as_view(),
        name='password_change',
    ),
    path(
        'accounts/password_change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='finance/password_change_done.html',
        ),
        name='password_change_done',
    ),

    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('finance.urls')),
]
